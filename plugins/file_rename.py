import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from PIL import Image
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InputMediaDocument, Message
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pymongo import MongoClient
from plugins.antinsfw import check_anti_nsfw
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import codeflixbots
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global dictionary to track ongoing operations
renaming_operations = {}

# Database setup for sequence mode
db_client = MongoClient(Config.DB_URL)
db = db_client[Config.DB_NAME]
sequence_collection = db["active_sequences"]

def is_in_sequence_mode(user_id):
    """Check if user is in sequence mode"""
    return sequence_collection.find_one({"user_id": user_id}) is not None

# Enhanced regex patterns for season and episode extraction
SEASON_EPISODE_PATTERNS = [
    # Standard patterns (S01E02, S01EP02) - Most specific first
    (re.compile(r'S(\d+)E(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)EP(\d+)', re.IGNORECASE), ('season', 'episode')),
    
    # Patterns with spaces/dashes (S01 E02, S01-EP02)
    (re.compile(r'S(\d+)[\s-]+E(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]+EP(\d+)', re.IGNORECASE), ('season', 'episode')),
    
    # Full text patterns (Season 1 Episode 2)
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    
    # Patterns with brackets/parentheses ([S01][E02])
    (re.compile(r'\[S(\d+)\]\[E(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    
    # Episode only patterns (Ep-01, Episode 01) - More specific
    (re.compile(r'Ep-(\d+)', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'Episode[\s-]*(\d+)', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'E(\d+)(?![0-9p])', re.IGNORECASE), (None, 'episode')),
    
    # Fallback patterns - exclude quality numbers (avoid 720, 1080, etc.)
    (re.compile(r'(?<![\d])\b(\d{1,2})\b(?!\d)(?![0-9]*p)(?!80)(?!20)', re.IGNORECASE), (None, 'episode')),
]

# Updated Quality detection patterns - more specific
QUALITY_PATTERNS = [
    # Quality with 'p' suffix (1080p, 720p, 480p)
    (re.compile(r'\b(\d{3,4}p)\b', re.IGNORECASE), lambda m: m.group(1)),
    
    # 4K and 2K patterns
    (re.compile(r'\b(4k|uhd|2160p)\b', re.IGNORECASE), lambda m: "4K"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2K"),
    
    # Quality descriptors
    (re.compile(r'\b(HDRip|HDTV|WEBRip|BluRay|BRRip|DVDRip)\b', re.IGNORECASE), lambda m: m.group(1)),
    
    # Bracketed quality [1080p], [720p]
    (re.compile(r'\[(\d{3,4}p)\]', re.IGNORECASE), lambda m: m.group(1)),
    
    # Quality numbers without p (720, 1080) - but be careful
    (re.compile(r'\b(720|1080|480|360|2160)\b', re.IGNORECASE), lambda m: f"{m.group(1)}p"),
]

def extract_season_episode(filename):
    """Extract season and episode numbers from filename"""
    logger.info(f"Processing filename: {filename}")
    
    for i, (pattern, (season_group, episode_group)) in enumerate(SEASON_EPISODE_PATTERNS):
        match = pattern.search(filename)
        if match:
            season = match.group(1) if season_group and len(match.groups()) >= 1 else None
            episode = match.group(2) if episode_group and len(match.groups()) >= 2 else match.group(1)
            
            # Validate episode number (should be reasonable)
            if episode and episode.isdigit():
                episode_num = int(episode)
                if episode_num > 0 and episode_num <= 999:  # Reasonable episode range
                    logger.info(f"Pattern {i}: Extracted season: {season}, episode: {episode} from {filename}")
                    return season, episode
                    
    logger.warning(f"No valid season/episode pattern matched for {filename}")
    return None, None

def extract_quality(filename):
    """Extract quality information from filename"""
    logger.info(f"Extracting quality from: {filename}")
    
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(filename)
        if match:
            quality = extractor(match)
            logger.info(f"Extracted quality: {quality} from {filename}")
            return quality
            
    logger.warning(f"No quality pattern matched for {filename}, using default")
    return "HD"

async def cleanup_files(*paths):
    """Safely remove files if they exist"""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Error removing {path}: {e}")

async def process_thumbnail(thumb_path):
    """Process and resize thumbnail image"""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    
    try:
        with Image.open(thumb_path) as img:
            img = img.convert("RGB").resize((320, 320))
            img.save(thumb_path, "JPEG")
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

async def add_metadata(input_path, output_path, user_id):
    """Add metadata to media file using ffmpeg"""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found in PATH")
    
    metadata = {
        'title': await codeflixbots.get_title(user_id),
        'artist': await codeflixbots.get_artist(user_id),
        'author': await codeflixbots.get_author(user_id),
        'video_title': await codeflixbots.get_video(user_id),
        'audio_title': await codeflixbots.get_audio(user_id),
        'subtitle': await codeflixbots.get_subtitle(user_id)
    }
    
    cmd = [
        ffmpeg,
        '-i', input_path,
        '-metadata', f'title={metadata["title"]}',
        '-metadata', f'artist={metadata["artist"]}',
        '-metadata', f'author={metadata["author"]}',
        '-metadata:s:v', f'title={metadata["video_title"]}',
        '-metadata:s:a', f'title={metadata["audio_title"]}',
        '-metadata:s:s', f'title={metadata["subtitle"]}',
        '-map', '0',
        '-c', 'copy',
        '-loglevel', 'error',
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    
    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()}")

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio), group=1)
async def auto_rename_files(client, message):
    """Main handler for auto-renaming files"""
    user_id = message.from_user.id
    
    # Check if user is in sequence mode - if so, let sequence handler take over
    if is_in_sequence_mode(user_id):
        return  # Let the sequence handler (group=0) handle this
    
    format_template = await codeflixbots.get_format_template(user_id)
    
    if not format_template:
        return await message.reply_text("Please set a rename format using /autorename")

    # Get file information
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
        file_size = message.document.file_size
        media_type = "document"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video"
        file_size = message.video.file_size
        media_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio"
        file_size = message.audio.file_size
        media_type = "audio"
    else:
        return await message.reply_text("Unsupported file type")

    # NSFW check
    if await check_anti_nsfw(file_name, message):
        return await message.reply_text("NSFW content detected")

    # Prevent duplicate processing
    if file_id in renaming_operations:
        if (datetime.now() - renaming_operations[file_id]).seconds < 10:
            return
    renaming_operations[file_id] = datetime.now()

    try:
        # Extract metadata from filename
        season, episode = extract_season_episode(file_name)
        quality = extract_quality(file_name)
        
        logger.info(f"Extracted - Season: {season}, Episode: {episode}, Quality: {quality}")
        
        # Replace placeholders in template
        new_template = format_template
        replacements = {
            '{season}': season if season else 'XX',
            '{episode}': episode if episode else 'XX',
            '{quality}': quality if quality else 'HD',
            'Season': season if season else 'XX',
            'Episode': episode if episode else 'XX',
            'QUALITY': quality if quality else 'HD'
        }
        
        for placeholder, value in replacements.items():
            new_template = new_template.replace(placeholder, str(value))

        # Prepare file paths
        ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
        new_filename = f"{new_template}{ext}"
        
        # Ensure directories exist
        downloads_dir = "downloads"
        metadata_dir = "metadata"
        os.makedirs(downloads_dir, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)
        
        download_path = os.path.join(downloads_dir, new_filename)
        metadata_path = os.path.join(metadata_dir, new_filename)

        logger.info(f"Download path: {download_path}")
        logger.info(f"Metadata path: {metadata_path}")

        # Download file
        msg = await message.reply_text("**Downloading...**")
        try:
            file_path = await client.download_media(
                message,
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time())
            )
            logger.info(f"Downloaded to: {file_path}")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            await msg.edit(f"Download failed: {e}")
            raise

        # Check if metadata is enabled
        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await msg.edit("**Processing metadata...**")
            try:
                await add_metadata(file_path, metadata_path, user_id)
                file_path = metadata_path
                logger.info(f"Metadata added, using: {file_path}")
            except Exception as e:
                logger.error(f"Metadata processing failed: {e}")
                await msg.edit(f"Metadata processing failed: {e}")

        # Get thumbnail
        thumb_path = None
        thumbnail = await codeflixbots.get_thumbnail(user_id)
        if thumbnail:
            try:
                thumb_path = await client.download_media(thumbnail)
                thumb_path = await process_thumbnail(thumb_path)
            except Exception as e:
                logger.error(f"Thumbnail processing failed: {e}")

        # Get caption
        caption = await codeflixbots.get_caption(user_id)
        if caption:
            try:
                # Get file info for caption formatting
                file_info = os.stat(file_path)
                file_size_bytes = file_info.st_size
                
                # Try to get duration if it's a video/audio file
                duration = "Unknown"
                try:
                    parser = createParser(file_path)
                    if parser:
                        metadata_info = extractMetadata(parser)
                        if metadata_info and metadata_info.has("duration"):
                            duration = str(metadata_info.get("duration"))
                except:
                    pass
                
                # Format caption
                caption = caption.format(
                    filename=new_filename,
                    filesize=humanbytes(file_size_bytes),
                    duration=duration
                )
            except Exception as e:
                logger.error(f"Caption formatting failed: {e}")
        else:
            caption = f"**{new_filename}**"

        # Get media preference
        media_preference = await codeflixbots.get_media_preference(user_id)
        
        # Upload file
        await msg.edit("**Uploading...**")
        try:
            if media_preference == "video" and media_type in ["video", "document"]:
                await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading...", msg, time.time())
                )
            elif media_preference == "audio" and media_type in ["audio", "document"]:
                await client.send_audio(
                    chat_id=message.chat.id,
                    audio=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading...", msg, time.time())
                )
            else:
                await client.send_document(
                    chat_id=message.chat.id,
                    document=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading...", msg, time.time())
                )
            
            await msg.edit("**✅ File renamed and uploaded successfully!**")
            
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            await msg.edit(f"Upload failed: {e}")
            raise

    except Exception as e:
        logger.error(f"Error in auto_rename_files: {e}")
        await message.reply_text(f"An error occurred: {str(e)}")
    
    finally:
        # Cleanup
        if file_id in renaming_operations:
            del renaming_operations[file_id]
        
        # Clean up temporary files
        await cleanup_files(download_path, metadata_path, thumb_path)
