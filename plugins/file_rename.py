import asyncio
import os
import time
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from pyrogram.errors import FloodWait, MessageNotModified
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from helper.utils import progress_for_pyrogram, convert, humanbytes
from helper.database import codeflixbots
from PIL import Image
import logging

logger = logging.getLogger(__name__)

# File extensions mapping for media type detection
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.mts'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.opus'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'}
DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.zip', '.rar', '.7z', '.tar', '.gz'}

async def get_upload_destination(user_id):
    """Get user's upload destination settings"""
    try:
        destination_info = await codeflixbots.get_upload_destination(user_id)
        upload_as_document = await codeflixbots.get_upload_mode(user_id)
        return destination_info, upload_as_document
    except Exception as e:
        logger.error(f"Error getting upload destination for user {user_id}: {e}")
        return None, False

def get_media_type(filename):
    """Determine media type based on file extension"""
    extension = os.path.splitext(filename.lower())[1]
    
    if extension in VIDEO_EXTENSIONS:
        return 'video'
    elif extension in AUDIO_EXTENSIONS:
        return 'audio'
    elif extension in IMAGE_EXTENSIONS:
        return 'photo'
    else:
        return 'document'

async def send_file_to_destination(client, user_id, file_path, filename, thumbnail=None, caption=None, message=None):
    """Send file to user's configured destination"""
    try:
        # Get destination settings
        destination_info, upload_as_document = await get_upload_destination(user_id)
        
        # Determine where to send
        if destination_info and destination_info.get('chat_id'):
            chat_id = destination_info['chat_id']
            topic_id = destination_info.get('topic_id')
            dest_name = destination_info.get('name', 'Unknown')
            upload_info = f"📤 Uploading to: {dest_name}"
        else:
            chat_id = user_id  # Send to private chat
            topic_id = None
            upload_info = "📤 Uploading to: Private Chat"
        
        # Update progress message if provided
        if message:
            try:
                await message.edit_text(f"{upload_info}\n\n⏱️ Starting upload...")
            except:
                pass
        
        # Get file size for progress
        file_size = os.path.getsize(file_path)
        
        # Send file based on upload mode and file type
        if upload_as_document:
            # Always send as document
            sent_file = await client.send_document(
                chat_id=chat_id,
                document=file_path,
                file_name=filename,
                thumb=thumbnail,
                caption=caption,
                message_thread_id=topic_id,
                progress=progress_for_pyrogram,
                progress_args=(f"{upload_info}\n\n📤 Uploading...", message, time.time())
            )
        else:
            # Send based on media type
            media_type = get_media_type(filename)
            
            if media_type == 'video':
                # Extract video metadata
                duration = 0
                width = 0
                height = 0
                
                try:
                    metadata = extractMetadata(createParser(file_path))
                    if metadata:
                        if metadata.has("duration"):
                            duration = metadata.get('duration').seconds
                        if metadata.has("width"):
                            width = metadata.get('width')
                        if metadata.has("height"):
                            height = metadata.get('height')
                except:
                    pass
                
                sent_file = await client.send_video(
                    chat_id=chat_id,
                    video=file_path,
                    file_name=filename,
                    duration=duration,
                    width=width,
                    height=height,
                    thumb=thumbnail,
                    caption=caption,
                    message_thread_id=topic_id,
                    progress=progress_for_pyrogram,
                    progress_args=(f"{upload_info}\n\n📤 Uploading video...", message, time.time())
                )
                
            elif media_type == 'audio':
                # Extract audio metadata
                duration = 0
                performer = ""
                title = ""
                
                try:
                    metadata = extractMetadata(createParser(file_path))
                    if metadata:
                        if metadata.has("duration"):
                            duration = metadata.get('duration').seconds
                        if metadata.has("author"):
                            performer = metadata.get('author')
                        if metadata.has("title"):
                            title = metadata.get('title')
                except:
                    pass
                
                sent_file = await client.send_audio(
                    chat_id=chat_id,
                    audio=file_path,
                    file_name=filename,
                    duration=duration,
                    performer=performer,
                    title=title,
                    thumb=thumbnail,
                    caption=caption,
                    message_thread_id=topic_id,
                    progress=progress_for_pyrogram,
                    progress_args=(f"{upload_info}\n\n📤 Uploading audio...", message, time.time())
                )
                
            elif media_type == 'photo' and file_size < 10 * 1024 * 1024:  # Less than 10MB
                sent_file = await client.send_photo(
                    chat_id=chat_id,
                    photo=file_path,
                    caption=caption,
                    message_thread_id=topic_id
                )
            else:
                # Send as document for other file types or large images
                sent_file = await client.send_document(
                    chat_id=chat_id,
                    document=file_path,
                    file_name=filename,
                    thumb=thumbnail,
                    caption=caption,
                    message_thread_id=topic_id,
                    progress=progress_for_pyrogram,
                    progress_args=(f"{upload_info}\n\n📤 Uploading document...", message, time.time())
                )
        
        return sent_file
        
    except FloodWait as e:
        logger.warning(f"FloodWait: {e.value} seconds")
        await asyncio.sleep(e.value)
        return await send_file_to_destination(client, user_id, file_path, filename, thumbnail, caption, message)
        
    except Exception as e:
        logger.error(f"Error sending file to destination: {e}")
        # Fallback to private chat
        try:
            if message:
                await message.edit_text("❌ Error uploading to destination. Sending to private chat...")
            
            return await client.send_document(
                chat_id=user_id,
                document=file_path,
                file_name=filename,
                thumb=thumbnail,
                caption=caption,
                progress=progress_for_pyrogram,
                progress_args=("📤 Uploading to private chat...", message, time.time())
            )
        except Exception as fallback_error:
            logger.error(f"Fallback upload also failed: {fallback_error}")
            if message:
                await message.edit_text(f"❌ Upload failed: {str(fallback_error)}")
            return None

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def rename_start(client, message):
    user_id = message.from_user.id
    
    # Check if user is in premium mode or has remaining renames
    try:
        user_data = await codeflixbots.find_one({"_id": user_id})
        if not user_data:
            await codeflixbots.add_user(client, message)
            user_data = await codeflixbots.find_one({"_id": user_id})
    except:
        await message.reply_text("❌ Database error. Please try again.")
        return
    
    # Check if user has active sequence
    try:
        sequence_data = await codeflixbots.get_user_sequence(user_id)
        if sequence_data and sequence_data.get('active', False):
            # Handle sequence processing
            await handle_sequence_file(client, message, sequence_data)
            return
    except:
        pass
    
    # Check queue status
    try:
        queue_data = await codeflixbots.get_user_queue(user_id)
        if queue_data and len(queue_data.get('files', [])) >= 10:
            await message.reply_text(
                "⚠️ Your queue is full (10 files max).\n"
                "Please wait for current files to process or use /clearqueue"
            )
            return
    except:
        pass
    
    # Check file size (2GB limit)
    if message.document:
        file_size = message.document.file_size
        file_name = message.document.file_name
    elif message.video:
        file_size = message.video.file_size
        file_name = getattr(message.video, 'file_name', 'video.mp4')
    elif message.audio:
        file_size = message.audio.file_size
        file_name = getattr(message.audio, 'file_name', 'audio.mp3')
    else:
        await message.reply_text("❌ Unsupported file type.")
        return
    
    if file_size > 2 * 1024 * 1024 * 1024:  # 2GB
        await message.reply_text("❌ File size too large. Maximum supported size is 2GB.")
        return
    
    # Check auto-rename setting
    try:
        auto_rename_data = await codeflixbots.get_auto_rename(user_id)
        if auto_rename_data and auto_rename_data.get('enabled', False):
            # Auto rename the file
            await auto_rename_file(client, message, auto_rename_data.get('format', '{file_name}'))
            return
    except:
        pass
    
    # Ask for new filename
    try:
        file_info = f"📁 **File Information:**\n"
        file_info += f"📄 **Name:** `{file_name}`\n"
        file_info += f"📊 **Size:** `{humanbytes(file_size)}`\n"
        file_info += f"📁 **Type:** `{file_name.split('.')[-1].upper() if '.' in file_name else 'Unknown'}`\n\n"
        file_info += "Please send the new filename with extension:"
        
        await message.reply_text(
            file_info,
            reply_to_message_id=message.id,
            reply_markup=ForceReply(True)
        )
    except Exception as e:
        logger.error(f"Error in rename_start: {e}")
        await message.reply_text("❌ Error processing file. Please try again.")

@Client.on_message(filters.private & filters.reply & filters.text)
async def rename_doc(client, message):
    user_id = message.from_user.id
    
    # Check if this is a reply to our rename request
    if not message.reply_to_message:
        return
    
    reply_message = message.reply_to_message
    if not (reply_message.document or reply_message.video or reply_message.audio):
        return
    
    new_name = message.text.strip()
    
    # Validate filename
    if not new_name:
        await message.reply_text("❌ Please provide a valid filename.")
        return
    
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        new_name = new_name.replace(char, '')
    
    if not new_name:
        await message.reply_text("❌ Invalid filename. Please try again.")
        return
    
    # Add to queue if enabled
    try:
        queue_data = await codeflixbots.get_user_queue(user_id)
        if queue_data and queue_data.get('enabled', False):
            await add_to_queue(client, message, reply_message, new_name)
            return
    except:
        pass
    
    # Process file immediately
    await process_file_rename(client, message, reply_message, new_name)

async def process_file_rename(client, message, file_message, new_name):
    """Process file renaming and upload"""
    user_id = message.from_user.id
    
    try:
        # Start processing message
        ms = await message.reply_text("⏳ Processing your request...")
        
        # Download file
        try:
            await ms.edit_text("📥 Downloading file...")
            
            download_path = f"downloads/{user_id}_{int(time.time())}"
            os.makedirs(download_path, exist_ok=True)
            
            if file_message.document:
                file_path = await client.download_media(
                    file_message.document,
                    file_name=f"{download_path}/temp_file",
                    progress=progress_for_pyrogram,
                    progress_args=("📥 Downloading...", ms, time.time())
                )
            elif file_message.video:
                file_path = await client.download_media(
                    file_message.video,
                    file_name=f"{download_path}/temp_file",
                    progress=progress_for_pyrogram,
                    progress_args=("📥 Downloading...", ms, time.time())
                )
            elif file_message.audio:
                file_path = await client.download_media(
                    file_message.audio,
                    file_name=f"{download_path}/temp_file",
                    progress=progress_for_pyrogram,
                    progress_args=("📥 Downloading...", ms, time.time())
                )
            else:
                await ms.edit_text("❌ Unsupported file type.")
                return
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            await ms.edit_text(f"❌ Download failed: {str(e)}")
            return
        
        # Rename file
        try:
            await ms.edit_text("🔄 Renaming file...")
            
            new_file_path = f"{download_path}/{new_name}"
            os.rename(file_path, new_file_path)
            file_path = new_file_path
            
        except Exception as e:
            logger.error(f"Rename error: {e}")
            await ms.edit_text(f"❌ Rename failed: {str(e)}")
            return
        
        # Get thumbnail
        thumbnail = None
        try:
            thumb_data = await codeflixbots.get_thumbnail(user_id)
            if thumb_data and thumb_data.get('file_id'):
                thumbnail = await client.download_media(thumb_data['file_id'])
        except:
            pass
        
        # Get caption
        caption = None
        try:
            caption_data = await codeflixbots.get_caption(user_id)
            if caption_data and caption_data.get('caption'):
                caption = caption_data['caption']
        except:
            pass
        
        # Apply metadata if enabled
        try:
            metadata_data = await codeflixbots.get_metadata(user_id)
            if metadata_data and metadata_data.get('enabled', False):
                await ms.edit_text("🏷️ Applying metadata...")
                file_path = await apply_metadata(file_path, metadata_data, new_name)
        except Exception as e:
            logger.warning(f"Metadata application failed: {e}")
        
        # Upload file to destination
        await ms.edit_text("📤 Uploading file...")
        
        sent_file = await send_file_to_destination(
            client, user_id, file_path, new_name, thumbnail, caption, ms
        )
        
        if sent_file:
            # Success message
            destination_info, _ = await get_upload_destination(user_id)
            if destination_info and destination_info.get('chat_id'):
                dest_name = destination_info.get('name', 'Unknown')
                success_msg = f"✅ **File uploaded successfully!**\n\n"
                success_msg += f"📁 **File:** `{new_name}`\n"
                success_msg += f"📍 **Destination:** {dest_name}\n"
                success_msg += f"🔗 **Message ID:** `{sent_file.id}`"
            else:
                success_msg = f"✅ **File renamed and uploaded successfully!**\n\n"
                success_msg += f"📁 **New name:** `{new_name}`"
            
            await ms.edit_text(success_msg)
        else:
            await ms.edit_text("❌ Upload failed. Please try again.")
        
        # Cleanup
        try:
            import shutil
            shutil.rmtree(download_path)
            if thumbnail and os.path.exists(thumbnail):
                os.remove(thumbnail)
        except:
            pass
            
    except Exception as e:
        logger.error(f"Error in process_file_rename: {e}")
        try:
            await ms.edit_text(f"❌ Error: {str(e)}")
        except:
            await message.reply_text(f"❌ Error: {str(e)}")

async def auto_rename_file(client, message, format_template):
    """Auto rename file using template"""
    user_id = message.from_user.id
    
    try:
        # Get original filename
        if message.document:
            original_name = message.document.file_name or "document"
        elif message.video:
            original_name = getattr(message.video, 'file_name', 'video.mp4')
        elif message.audio:
            original_name = getattr(message.audio, 'file_name', 'audio.mp3')
        else:
            return
        
        # Get file extension
        file_extension = os.path.splitext(original_name)[1]
        file_name_without_ext = os.path.splitext(original_name)[0]
        
        # Get sequence number if active
        sequence_num = ""
        try:
            sequence_data = await codeflixbots.get_user_sequence(user_id)
            if sequence_data and sequence_data.get('active', False):
                current_num = sequence_data.get('current_number', 1)
                sequence_num = str(current_num).zfill(sequence_data.get('padding', 2))
                # Update sequence number
                await codeflixbots.update_sequence_number(user_id, current_num + 1)
        except:
            pass
        
        # Replace placeholders in template
        new_name = format_template.replace('{file_name}', file_name_without_ext)
        new_name = new_name.replace('{extension}', file_extension)
        new_name = new_name.replace('{sequence}', sequence_num)
        
        # Add extension if not present
        if not new_name.endswith(file_extension):
            new_name += file_extension
        
        # Process the file
        await process_file_rename(client, message, message, new_name)
        
    except Exception as e:
        logger.error(f"Auto rename error: {e}")
        await message.reply_text(f"❌ Auto rename failed: {str(e)}")

async def handle_sequence_file(client, message, sequence_data):
    """Handle file in sequence mode"""
    user_id = message.from_user.id
    
    try:
        # Get sequence settings
        current_num = sequence_data.get('current_number', 1)
        padding = sequence_data.get('padding', 2)
        prefix = sequence_data.get('prefix', '')
        suffix = sequence_data.get('suffix', '')
        
        # Get file extension
        if message.document:
            original_name = message.document.file_name or "document"
        elif message.video:
            original_name = getattr(message.video, 'file_name', 'video.mp4')
        elif message.audio:
            original_name = getattr(message.audio, 'file_name', 'audio.mp3')
        else:
            return
        
        file_extension = os.path.splitext(original_name)[1]
        
        # Generate new filename
        sequence_num = str(current_num).zfill(padding)
        new_name = f"{prefix}{sequence_num}{suffix}{file_extension}"
        
        # Update sequence number
        await codeflixbots.update_sequence_number(user_id, current_num + 1)
        
        # Process the file
        await process_file_rename(client, message, message, new_name)
        
    except Exception as e:
        logger.error(f"Sequence handling error: {e}")
        await message.reply_text(f"❌ Sequence processing failed: {str(e)}")

async def add_to_queue(client, message, file_message, new_name):
    """Add file to processing queue"""
    user_id = message.from_user.id
    
    try:
        # Get current queue
        queue_data = await codeflixbots.get_user_queue(user_id)
        current_files = queue_data.get('files', []) if queue_data else []
        
        if len(current_files) >= 10:
            await message.reply_text(
                "⚠️ Queue is full (10 files max).\n"
                "Please wait for current files to process."
            )
            return
        
        # Add file to queue
        file_info = {
            'message_id': file_message.id,
            'new_name': new_name,
            'added_time': time.time()
        }
        
        current_files.append(file_info)
        await codeflixbots.set_user_queue(user_id, {'files': current_files, 'enabled': True})
        
        await message.reply_text(
            f"✅ **File added to queue!**\n\n"
            f"📁 **Name:** `{new_name}`\n"
            f"📊 **Queue position:** `{len(current_files)}`\n"
            f"⏳ **Status:** Waiting\n\n"
            "Use /queueinfo to check queue status."
        )
        
    except Exception as e:
        logger.error(f"Queue error: {e}")
        await message.reply_text(f"❌ Queue error: {str(e)}")

async def apply_metadata(file_path, metadata_data, filename):
    """Apply metadata to file"""
    try:
        # This is a placeholder for metadata application
        # You can use ffmpeg or similar tools here
        
        # For now, just return the original file path
        return file_path
        
    except Exception as e:
        logger.error(f"Metadata application error: {e}")
        return file_path
