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

# Global dictionary to track ongoing operations and semaphores
renaming_operations = {}
user_operations = {}
download_semaphore = asyncio.Semaphore(5)  # Max 5 concurrent downloads globally
upload_semaphore = asyncio.Semaphore(3)    # Max 3 concurrent uploads globally

# Per-user limits
MAX_CONCURRENT_PER_USER = 3
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB limit

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

async def can_start_operation(user_id):
    """Check if user can start a new file operation"""
    current_operations = user_operations.get(user_id, 0)
    return current_operations < MAX_CONCURRENT_PER_USER

async def increment_user_operations(user_id):
    """Increment user operation count"""
    user_operations[user_id] = user_operations.get(user_id, 0) + 1

async def decrement_user_operations(user_id):
    """Decrement user operation count"""
    if user_id in user_operations:
        user_operations[user_id] = max(0, user_operations[user_id] - 1)
        if user_operations[user_id] == 0:
            del user_operations[user_id]

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
                logger.info(f"Cleaned up file: {path}")
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
        logger.info(f"Thumbnail processed successfully: {thumb_path}")
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
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg error: {stderr.decode()}")
        
        logger.info(f"Metadata added successfully to: {output_path}")
    except Exception as e:
        logger.error(f"Failed to add metadata: {e}")
        raise

async def process_single_file(client, message, file_info, format_template):
    """Process a single file with concurrent handling"""
    user_id = message.from_user.id
    file_id, file_name, file_size, media_type = file_info
    
    # Generate unique identifiers for this operation
    operation_id = f"{user_id}_{file_id}_{int(time.time())}"
    
    # File paths
    download_path = f"downloads/{operation_id}_{file_name}"
    output_path = f"outputs/{operation_id}_renamed_{file_name}"
    thumb_path = None
    
    # Progress message
    progress_msg = await message.reply_text(
        f"🔄 **Processing:** `{file_name}`\n📊 **Queue Position:** Processing...",
        quote=True
    )
    
    try:
        # Create directories if they don't exist
        os.makedirs("downloads", exist_ok=True)
        os.makedirs("outputs", exist_ok=True)
        
        # Extract metadata from filename
        season, episode = extract_season_episode(file_name)
        quality = extract_quality(file_name)
        
        logger.info(f"[{operation_id}] Extracted - Season: {season}, Episode: {episode}, Quality: {quality}")
        
        # Replace placeholders in template
        new_template = format_template
        replacements = {
            '{season}': season if season else 'XX',
            '{episode}': episode if episode else '01',
            '{quality}': quality,
            'season': season if season else 'XX',
            'episode': episode if episode else '01',
            'quality': quality,
            'Sseason': f"S{season.zfill(2)}" if season else "SXX",
            'Eepisode': f"E{episode.zfill(2)}" if episode else "E01"
        }
        
        for placeholder, value in replacements.items():
            new_template = new_template.replace(f'{{{placeholder}}}', str(value))
            new_template = new_template.replace(placeholder, str(value))
        
        # Get file extension
        file_extension = os.path.splitext(file_name)[1]
        new_filename = f"{new_template}{file_extension}"
        
        logger.info(f"[{operation_id}] New filename: {new_filename}")
        
        # Update progress
        await progress_msg.edit_text(f"⬇️ **Downloading:** `{file_name}`\n📁 **New name:** `{new_filename}`")
        
        # Download file with semaphore
        async with download_semaphore:
            try:
                start_time = time.time()
                download_path = await client.download_media(
                    message,
                    file_name=download_path,
                    progress=progress_for_pyrogram,
                    progress_args=("⬇️ **Downloading...**", progress_msg, start_time)
                )
                logger.info(f"[{operation_id}] Download completed: {download_path}")
            except Exception as e:
                logger.error(f"[{operation_id}] Download failed: {e}")
                raise
        
        # Update progress
        await progress_msg.edit_text(f"🔧 **Processing:** `{new_filename}`\n⚙️ **Adding metadata...**")
        
        # Get thumbnail
        thumbnail_file_id = await codeflixbots.get_thumbnail(user_id)
        if thumbnail_file_id:
            try:
                thumb_path = f"thumbnails/{operation_id}_thumb.jpg"
                os.makedirs("thumbnails", exist_ok=True)
                await client.download_media(thumbnail_file_id, file_name=thumb_path)
                thumb_path = await process_thumbnail(thumb_path)
                logger.info(f"[{operation_id}] Thumbnail processed: {thumb_path}")
            except Exception as e:
                logger.error(f"[{operation_id}] Thumbnail processing failed: {e}")
                thumb_path = None
        
        # Apply metadata if enabled
        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            try:
                await add_metadata(download_path, output_path, user_id)
                # Remove original file and use the one with metadata
                await cleanup_files(download_path)
                download_path = output_path
                logger.info(f"[{operation_id}] Metadata applied successfully")
            except Exception as e:
                logger.warning(f"[{operation_id}] Metadata application failed: {e}")
                # Continue with original file if metadata fails
        
        # Update progress
        await progress_msg.edit_text(f"⬆️ **Uploading:** `{new_filename}`\n📤 **Preparing upload...**")
        
        # Get user's media preference
        media_preference = await codeflixbots.get_media_preference(user_id)
        
        # Determine upload type
        if media_preference:
            upload_as = media_preference.lower()
        else:
            upload_as = media_type
        
        # Get custom caption
        custom_caption = await codeflixbots.get_caption(user_id)
        if custom_caption:
            # Extract file metadata for caption
            duration = "Unknown"
            if media_type in ["video", "audio"]:
                try:
                    parser = createParser(download_path)
                    if parser:
                        metadata = extractMetadata(parser)
                        if metadata and metadata.has("duration"):
                            duration = str(metadata.get("duration"))
                except Exception as e:
                    logger.warning(f"[{operation_id}] Metadata extraction failed: {e}")
            
            caption = custom_caption.format(
                filename=new_filename,
                filesize=humanbytes(file_size),
                duration=duration
            )
        else:
            caption = f"**File:** `{new_filename}`\n**Size:** `{humanbytes(file_size)}`"
        
        # Upload with semaphore
        async with upload_semaphore:
            try:
                start_time = time.time()
                if upload_as == "document":
                    await client.send_document(
                        chat_id=message.chat.id,
                        document=download_path,
                        thumb=thumb_path,
                        caption=caption,
                        progress=progress_for_pyrogram,
                        progress_args=("⬆️ **Uploading...**", progress_msg, start_time),
                        file_name=new_filename
                    )
                elif upload_as == "video":
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=download_path,
                        thumb=thumb_path,
                        caption=caption,
                        progress=progress_for_pyrogram,
                        progress_args=("⬆️ **Uploading...**", progress_msg, start_time),
                        file_name=new_filename
                    )
                elif upload_as == "audio":
                    await client.send_audio(
                        chat_id=message.chat.id,
                        audio=download_path,
                        thumb=thumb_path,
                        caption=caption,
                        progress=progress_for_pyrogram,
                        progress_args=("⬆️ **Uploading...**", progress_msg, start_time),
                        file_name=new_filename
                    )
                
                logger.info(f"[{operation_id}] Upload completed successfully")
                
                # Success message
                await progress_msg.edit_text(
                    f"✅ **Completed:** `{new_filename}`\n"
                    f"📁 **Original:** `{file_name}`\n"
                    f"📊 **Size:** `{humanbytes(file_size)}`"
                )
                
            except FloodWait as e:
                logger.warning(f"[{operation_id}] FloodWait: {e.value} seconds")
                await asyncio.sleep(e.value)
                # Retry upload after wait
                await process_single_file(client, message, file_info, format_template)
            except Exception as e:
                logger.error(f"[{operation_id}] Upload failed: {e}")
                raise
    
    except Exception as e:
        logger.error(f"[{operation_id}] Processing failed: {e}")
        await progress_msg.edit_text(
            f"❌ **Failed:** `{file_name}`\n"
            f"🔥 **Error:** `{str(e)[:100]}...`"
        )
    
    finally:
        # Cleanup files
        await cleanup_files(download_path, output_path, thumb_path)
        
        # Remove from tracking
        if file_id in renaming_operations:
            del renaming_operations[file_id]
        
        logger.info(f"[{operation_id}] Processing completed and cleaned up")

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    """Main handler for auto-renaming files with concurrent processing"""
    user_id = message.from_user.id
    format_template = await codeflixbots.get_format_template(user_id)
    
    if not format_template:
        return await message.reply_text(
            "📝 **Please set a rename format first using:**\n"
            "`/autorename Your Format Here`\n\n"
            "**Example:** `/autorename Anime [S{season}E{episode}] - {quality}`"
        )

    # Check if user can start new operation
    if not await can_start_operation(user_id):
        current_count = user_operations.get(user_id, 0)
        return await message.reply_text(
            f"⚠️ **Too many files processing!**\n"
            f"📊 **Current:** {current_count}/{MAX_CONCURRENT_PER_USER}\n"
            f"⏳ **Please wait for some files to complete.**"
        )

    # Get file information
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "document"
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
        return await message.reply_text("❌ **Unsupported file type**")

    # Check file size
    if file_size > MAX_FILE_SIZE:
        return await message.reply_text(
            f"❌ **File too large!**\n"
            f"📊 **Size:** `{humanbytes(file_size)}`\n"
            f"📏 **Limit:** `{humanbytes(MAX_FILE_SIZE)}`"
        )

    # NSFW check
    if await check_anti_nsfw(file_name, message):
        return

    # Prevent duplicate processing
    if file_id in renaming_operations:
        time_diff = (datetime.now() - renaming_operations[file_id]).seconds
        if time_diff < 30:  # Prevent duplicate within 30 seconds
            return await message.reply_text("⚠️ **This file is already being processed!**")

    # Mark operation as started
    renaming_operations[file_id] = datetime.now()
    await increment_user_operations(user_id)

    try:
        # Show queue status
        current_operations = user_operations.get(user_id, 0)
        queue_msg = await message.reply_text(
            f"🔄 **File Added to Queue**\n"
            f"📁 **File:** `{file_name}`\n"
            f"📊 **Your Queue:** {current_operations}/{MAX_CONCURRENT_PER_USER}\n"
            f"⏳ **Starting processing...**"
        )
        
        # Delete queue message after 3 seconds
        asyncio.create_task(delete_message_after_delay(queue_msg, 3))
        
        # File info tuple
        file_info = (file_id, file_name, file_size, media_type)
        
        # Start processing in background task
        asyncio.create_task(
            process_file_with_cleanup(client, message, file_info, format_template, user_id)
        )
        
    except Exception as e:
        logger.error(f"Error starting file processing: {e}")
        await decrement_user_operations(user_id)
        if file_id in renaming_operations:
            del renaming_operations[file_id]
        await message.reply_text(f"❌ **Failed to start processing:** `{str(e)}`")

async def process_file_with_cleanup(client, message, file_info, format_template, user_id):
    """Wrapper for file processing with proper cleanup"""
    try:
        await process_single_file(client, message, file_info, format_template)
    except Exception as e:
        logger.error(f"File processing error: {e}")
    finally:
        await decrement_user_operations(user_id)

async def delete_message_after_delay(message, delay):
    """Delete a message after specified delay"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

# Admin command to check queue status
@Client.on_message(filters.private & filters.command("queue") & filters.user(Config.ADMIN))
async def check_queue_status(client, message):
    """Admin command to check processing queue status"""
    global_operations = sum(user_operations.values())
    active_users = len(user_operations)
    
    queue_info = "🔄 **Queue Status**\n\n"
    queue_info += f"🌐 **Global Operations:** {global_operations}\n"
    queue_info += f"👥 **Active Users:** {active_users}\n"
    queue_info += f"⬇️ **Download Slots:** {download_semaphore._value}/{5}\n"
    queue_info += f"⬆️ **Upload Slots:** {upload_semaphore._value}/{3}\n\n"
    
    if user_operations:
        queue_info += "**User Operations:**\n"
        for user_id, count in user_operations.items():
            queue_info += f"• `{user_id}`: {count} files\n"
    else:
        queue_info += "✅ **No active operations**"
    
    await message.reply_text(queue_info)

# User command to check personal queue
@Client.on_message(filters.private & filters.command("myqueue"))
async def check_my_queue(client, message):
    """User command to check their processing status"""
    user_id = message.from_user.id
    current_operations = user_operations.get(user_id, 0)
    
    status_info = f"🔄 **Your Queue Status**\n\n"
    status_info += f"📊 **Active Files:** {current_operations}/{MAX_CONCURRENT_PER_USER}\n"
    
    if current_operations == 0:
        status_info += "✅ **No files processing**\n"
        status_info += "📤 **Ready for new files!**"
    else:
        status_info += f"⏳ **Available Slots:** {MAX_CONCURRENT_PER_USER - current_operations}\n"
        status_info += "🔄 **Files are being processed...**"
    
    await message.reply_text(status_info)
