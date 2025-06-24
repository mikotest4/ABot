import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from collections import deque
from dataclasses import dataclass
from typing import Optional
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

# ================== QUEUE MANAGEMENT SYSTEM ==================
@dataclass
class FileTask:
    message: Message
    user_id: int
    timestamp: float
    original_filename: str
    file_size: int

# Global dictionaries for queue management
user_queues = {}  # {user_id: deque([FileTask, ...])}
active_tasks = {}  # {user_id: {task_id: asyncio.Task}}
processing_stats = {}  # {user_id: {"active": 0, "queued": 0}}

MAX_CONCURRENT_PER_USER = 3

def get_filename(message: Message) -> str:
    """Extract filename from message"""
    if message.document:
        return message.document.file_name
    elif message.video:
        return message.video.file_name or "video"
    elif message.audio:
        return message.audio.file_name or "audio"
    return "file"

def get_file_size(message: Message) -> int:
    """Get file size from message"""
    if message.document:
        return message.document.file_size
    elif message.video:
        return message.video.file_size
    elif message.audio:
        return message.audio.file_size
    return 0

async def add_to_queue(client: Client, file_task: FileTask):
    """Add file task to user's processing queue"""
    user_id = file_task.user_id
    
    # Initialize user's queue if not exists
    if user_id not in user_queues:
        user_queues[user_id] = deque()
        active_tasks[user_id] = {}
        processing_stats[user_id] = {"active": 0, "queued": 0}
    
    # Add to queue and update stats
    user_queues[user_id].append(file_task)
    processing_stats[user_id]["queued"] = len(user_queues[user_id])
    
    await send_queue_status(file_task.message, user_id)
    await try_start_processing(client, user_id)

async def try_start_processing(client: Client, user_id: int):
    """Start processing tasks if capacity available"""
    # Check if we can start new tasks
    if (processing_stats[user_id]["active"] >= MAX_CONCURRENT_PER_USER or 
            not user_queues[user_id]):
        return
    
    # Start new tasks until capacity is reached
    while (processing_stats[user_id]["active"] < MAX_CONCURRENT_PER_USER and 
           user_queues[user_id]):
        file_task = user_queues[user_id].popleft()
        processing_stats[user_id]["queued"] = len(user_queues[user_id])
        
        # Create unique task ID
        task_id = f"{user_id}_{time.time()}"
        task = asyncio.create_task(
            process_single_file(client, file_task, task_id)
        )
        
        # Register active task
        active_tasks[user_id][task_id] = task
        processing_stats[user_id]["active"] = len(active_tasks[user_id])
        
        # Update queue status
        await send_queue_status(file_task.message, user_id)

async def process_single_file(client: Client, file_task: FileTask, task_id: str):
    """Process individual file (core renaming logic)"""
    message = file_task.message
    user_id = file_task.user_id
    file_name = file_task.original_filename
    
    try:
        format_template = await codeflixbots.get_format_template(user_id)
        if not format_template:
            await message.reply_text("❌ Please set a rename format using /autorename")
            return

        # NSFW check
        if await check_anti_nsfw(file_name, message):
            return await message.reply_text("🚫 NSFW content detected")

        # Extract metadata from filename
        season, episode = extract_season_episode(file_name)
        quality = extract_quality(file_name)
        
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
        ext = os.path.splitext(file_name)[1] or ('.mp4' if message.video else '.mp3')
        new_filename = f"{new_template}{ext}"
        
        # Download paths
        downloads_dir = "downloads"
        metadata_dir = "metadata"
        os.makedirs(downloads_dir, exist_ok=True)
        os.makedirs(metadata_dir, exist_ok=True)
        
        download_path = os.path.join(downloads_dir, new_filename)
        metadata_path = os.path.join(metadata_dir, new_filename)

        # Download file
        msg = await message.reply_text("📥 **Downloading...**")
        try:
            file_path = await client.download_media(
                message,
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time())
            )
        except Exception as e:
            await msg.edit(f"❌ Download failed: {e}")
            raise

        # Metadata processing
        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await msg.edit("🛠 **Processing metadata...**")
            try:
                await add_metadata(file_path, metadata_path, user_id)
                file_path = metadata_path
            except Exception as e:
                await msg.edit(f"❌ Metadata processing failed: {e}")

        # Thumbnail processing
        thumb_path = None
        thumbnail = await codeflixbots.get_thumbnail(user_id)
        if thumbnail:
            try:
                thumb_path = await client.download_media(thumbnail)
                thumb_path = await process_thumbnail(thumb_path)
            except Exception as e:
                logger.error(f"Thumbnail error: {e}")

        # Prepare caption
        caption = await codeflixbots.get_caption(user_id)
        if caption:
            try:
                file_size_bytes = os.stat(file_path).st_size
                duration = "Unknown"
                try:
                    parser = createParser(file_path)
                    if parser:
                        metadata_info = extractMetadata(parser)
                        if metadata_info and metadata_info.has("duration"):
                            duration = str(metadata_info.get("duration"))
                except:
                    pass
                
                caption = caption.format(
                    filename=new_filename,
                    filesize=humanbytes(file_size_bytes),
                    duration=duration
                )
            except Exception as e:
                logger.error(f"Caption error: {e}")
                caption = f"**{new_filename}**"
        else:
            caption = f"**{new_filename}**"

        # Upload file
        await msg.edit("📤 **Uploading...**")
        media_preference = await codeflixbots.get_media_preference(user_id)
        
        try:
            if media_preference == "video" and (message.video or message.document):
                await client.send_video(
                    chat_id=message.chat.id,
                    video=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    progress=progress_for_pyrogram,
                    progress_args=("Uploading...", msg, time.time())
                )
            elif media_preference == "audio" and (message.audio or message.document):
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
            
            await msg.edit("✅ **File renamed and uploaded successfully!**")
            
        except Exception as e:
            await msg.edit(f"❌ Upload failed: {e}")
            raise

    except Exception as e:
        logger.error(f"Processing error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")
    
    finally:
        # Cleanup temporary files
        await cleanup_files(download_path, metadata_path, thumb_path)
        
        # Update task tracking
        del active_tasks[user_id][task_id]
        processing_stats[user_id]["active"] = len(active_tasks[user_id])
        await try_start_processing(client, user_id)
        await send_queue_status(message, user_id)

async def send_queue_status(message: Message, user_id: int):
    """Send current queue status to user"""
    stats = processing_stats.get(user_id, {"active": 0, "queued": 0})
    status_msg = (
        "📊 **Processing Status**\n"
        f"• Active tasks: `{stats['active']}`\n"
        f"• Queued files: `{stats['queued']}`"
    )
    await message.reply_text(status_msg, quote=True)

# ================== ORIGINAL HELPER FUNCTIONS ==================
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
    (re.compile(r'S(\d+)E(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)EP(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]+E(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]+EP(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'\[S(\d+)\]\[E(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Ep-(\d+)', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'Episode[\s-]*(\d+)', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'E(\d+)(?![0-9p])', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'(?<![\d])\b(\d{1,2})\b(?!\d)(?![0-9]*p)(?!80)(?!20)', re.IGNORECASE), (None, 'episode')),
]

# Updated Quality detection patterns
QUALITY_PATTERNS = [
    (re.compile(r'\b(\d{3,4}p)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\b(4k|uhd|2160p)\b', re.IGNORECASE), lambda m: "4K"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2K"),
    (re.compile(r'\b(HDRip|HDTV|WEBRip|BluRay|BRRip|DVDRip)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\[(\d{3,4}p)\]', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\b(720|1080|480|360|2160)\b', re.IGNORECASE), lambda m: f"{m.group(1)}p"),
]

def extract_season_episode(filename):
    """Extract season and episode numbers from filename"""
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
        match = pattern.search(filename)
        if match:
            season = match.group(1) if season_group and len(match.groups()) >= 1 else None
            episode = match.group(2) if episode_group and len(match.groups()) >= 2 else match.group(1)
            if episode and episode.isdigit() and 0 < int(episode) <= 999:
                return season, episode
    return None, None

def extract_quality(filename):
    """Extract quality information from filename"""
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(filename)
        if match:
            return extractor(match)
    return "HD"

async def cleanup_files(*paths):
    """Safely remove files if they exist"""
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

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
        logger.error(f"Thumbnail error: {e}")
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

# ================== MAIN HANDLER ==================
@Client.on_message(filters.private & (filters.document | filters.video | filters.audio), group=1)
async def enhanced_rename_handler(client, message):
    """Enhanced handler with queue management"""
    user_id = message.from_user.id
    
    # Skip if in sequence mode
    if is_in_sequence_mode(user_id):
        return
    
    # Create file task
    file_task = FileTask(
        message=message,
        user_id=user_id,
        timestamp=time.time(),
        original_filename=get_filename(message),
        file_size=get_file_size(message)
    )
    
    # Add to processing queue
    await add_to_queue(client, file_task)
