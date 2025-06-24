import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
import re
from collections import defaultdict
from pymongo import MongoClient
from datetime import datetime
from config import Config

# Database setup
db_client = MongoClient(Config.DB_URL)
db = db_client[Config.DB_NAME]
users_collection = db["users_sequence"]
sequence_collection = db["active_sequences"]

# Patterns for extracting episode numbers
patterns = [
    re.compile(r'\b(?:EP|E)\s*-\s*(\d{1,3})\b', re.IGNORECASE),  # "Ep - 06" format fix
    re.compile(r'\b(?:EP|E)\s*(\d{1,3})\b', re.IGNORECASE),  # "EP06" or "E 06"
    re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE),  # "S1E06" / "S01EP06"
    re.compile(r'S(\d+)\s*(?:E|EP|-\s*EP)\s*(\d+)', re.IGNORECASE),  # "S 1 Ep 06"
    re.compile(r'(?:[([<{]?\s*(?:E|EP)\s*(\d+)\s*[)\]>}]?)', re.IGNORECASE),  # "E(06)"
    re.compile(r'(?:EP|E)?\s*[-]?\s*(\d{1,3})', re.IGNORECASE),  # "E - 06" / "- 06"
    re.compile(r'S(\d+)[^\d]*(\d+)', re.IGNORECASE),  # "S1 - 06"
    re.compile(r'(\d+)')  # Simple fallback (last resort)
]

def extract_episode_number(filename):
    """Extract episode number from filename for sorting"""
    for pattern in patterns:
        match = pattern.search(filename)
        if match:
            return int(match.groups()[-1])
    return float('inf')  

def is_in_sequence_mode(user_id):
    """Check if user is in sequence mode"""
    return sequence_collection.find_one({"user_id": user_id}) is not None

@Client.on_message(filters.private & filters.command("startsequence"))
async def start_sequence(client, message):
    user_id = message.from_user.id
    
    # Check if already in sequence mode
    if is_in_sequence_mode(user_id):
        await message.reply_text("⚠️ Sequence mode is already active. Send your files or use /endsequence.")
        return
        
    # Create new sequence entry
    sequence_collection.insert_one({
        "user_id": user_id,
        "files": [],
        "started_at": datetime.now()
    })
    
    await message.reply_text("✅ Sequence mode started! Send your files now.")

@Client.on_message(filters.private & filters.command("endsequence"))
async def end_sequence(client, message):
    user_id = message.from_user.id
    
    # Get sequence data
    sequence_data = sequence_collection.find_one({"user_id": user_id})
    
    if not sequence_data or not sequence_data.get("files"):
        await message.reply_text("❌ No files in sequence!")
        return
    
    # Get files and sort them
    files = sequence_data.get("files", [])
    sorted_files = sorted(files, key=lambda x: extract_episode_number(x["filename"]))
    total = len(sorted_files)
    
    # Send progress message
    progress = await message.reply_text(f"⏳ Processing and sorting {total} files...")
    
    sent_count = 0
    
    # Send files in sequence
    for i, file in enumerate(sorted_files, 1):
        try:
            await client.copy_message(
                chat_id=message.chat.id, 
                from_chat_id=file["chat_id"], 
                message_id=file["msg_id"]
            )
            sent_count += 1
            
            # Update progress every 5 files
            if i % 5 == 0:
                await progress.edit_text(f"📤 Sent {i}/{total} files...")
            
            await asyncio.sleep(0.5)  # Add delay to prevent flooding
        except Exception as e:
            print(f"Error sending file: {e}")
    
    # Update user stats
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"files_sequenced": sent_count}, 
         "$set": {"username": message.from_user.first_name}},
        upsert=True
    )
    
    # Remove sequence data
    sequence_collection.delete_one({"user_id": user_id})
    
    await progress.edit_text(f"✅ Successfully sent {sent_count} files in sequence!")

# File handler with higher group priority to ensure it runs before rename handler
@Client.on_message(filters.private & (filters.document | filters.video | filters.audio), group=-1)
async def sequence_file_handler(client, message):
    user_id = message.from_user.id
    
    # Check if user is in sequence mode
    if is_in_sequence_mode(user_id):
        # Get file name based on media type
        if message.document:
            file_name = message.document.file_name
        elif message.video:
            file_name = message.video.file_name or "video"
        elif message.audio:
            file_name = message.audio.file_name or "audio"
        else:
            file_name = "Unknown"
        
        # Store file information
        file_info = {
            "filename": file_name,
            "msg_id": message.id,
            "chat_id": message.chat.id,
            "added_at": datetime.now()
        }
        
        # Add to sequence collection
        sequence_collection.update_one(
            {"user_id": user_id},
            {"$push": {"files": file_info}}
        )
        
        # Set flag to indicate this is for sequence
        message.stop_propagation()
        
        await message.reply_text(f"📂 Added to sequence: {file_name}")

@Client.on_message(filters.private & filters.command("cancelsequence"))
async def cancel_sequence(client, message):
    user_id = message.from_user.id
    
    # Remove sequence data
    result = sequence_collection.delete_one({"user_id": user_id})
    
    if result.deleted_count > 0:
        await message.reply_text("❌ Sequence mode cancelled. All queued files have been cleared.")
    else:
        await message.reply_text("❓ No active sequence found to cancel.")

@Client.on_message(filters.private & filters.command("showsequence"))
async def show_sequence(client, message):
    user_id = message.from_user.id
    
    # Get sequence data
    sequence_data = sequence_collection.find_one({"user_id": user_id})
    
    if not sequence_data or not sequence_data.get("files"):
        await message.reply_text("📋 **No files in sequence**")
        return
    
    files = sequence_data.get("files", [])
    files_list = []
    
    for i, file in enumerate(files, 1):
        episode_num = extract_episode_number(file["filename"])
        if episode_num != float('inf'):
            files_list.append(f"{i}. {file['filename']} (Episode {episode_num})")
        else:
            files_list.append(f"{i}. {file['filename']} (No episode detected)")
    
    # Limit display to first 10 files
    display_files = files_list[:10]
    if len(files_list) > 10:
        display_files.append(f"... and {len(files_list) - 10} more files")
    
    files_text = "\n".join(display_files)
    
    await message.reply_text(
        f"📋 **Files in Sequence ({len(files)} total):**\n\n{files_text}\n\n"
        f"Use /endsequence to process all files in episode order."
    )

@Client.on_message(filters.private & filters.command("leaderboard"))
async def show_leaderboard(client, message):
    # Get top 10 users by files sequenced
    top_users = users_collection.find().sort("files_sequenced", -1).limit(10)
    
    leaderboard_text = "🏆 **Top Users - Files Sequenced**\n\n"
    
    for i, user in enumerate(top_users, 1):
        username = user.get("username", "Unknown")
        files_count = user.get("files_sequenced", 0)
        
        if i == 1:
            leaderboard_text += f"🥇 {username}: {files_count} files\n"
        elif i == 2:
            leaderboard_text += f"🥈 {username}: {files_count} files\n"
        elif i == 3:
            leaderboard_text += f"🥉 {username}: {files_count} files\n"
        else:
            leaderboard_text += f"{i}. {username}: {files_count} files\n"
    
    if not leaderboard_text.strip().endswith("files"):
        leaderboard_text += "No users found in leaderboard yet!"
    
    await message.reply_text(leaderboard_text)
