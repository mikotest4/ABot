import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from pyrogram.errors import ChatAdminRequired, UserNotParticipant, PeerIdInvalid
from helper.database import codeflixbots
from config import Config

# Store temporary states for users waiting for destination input
waiting_for_destination = {}

@Client.on_message(filters.private & filters.command("settings"))
async def settings_command(client, message):
    """Main settings command handler"""
    user_id = message.from_user.id
    
    # Get current user settings
    upload_as_document = await codeflixbots.get_upload_mode(user_id)
    destination_info = await codeflixbots.get_upload_destination(user_id)
    
    # Format upload mode text
    upload_mode_text = "Send As Document ✅" if upload_as_document else "Send As Media ✅"
    
    # Format destination text
    if destination_info and destination_info.get('chat_id'):
        dest_name = destination_info.get('name', 'Unknown Channel/Group')
        destination_text = f"📍 Destination: {dest_name}"
    else:
        destination_text = "📍 Destination: Private Chat (Default)"
    
    settings_text = f"""🔧 **Bot Settings**

**Current Configuration:**
📤 Upload Mode: {upload_mode_text}
{destination_text}

Choose an option to modify:"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📤 Send As Document" if not upload_as_document else "📤 Send As Media", 
                callback_data="toggle_upload_mode"
            ),
            InlineKeyboardButton("📍 Set Upload Destination", callback_data="set_destination")
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
        ]
    ])
    
    await message.reply_text(settings_text, reply_markup=keyboard)

@Client.on_callback_query(filters.regex("toggle_upload_mode"))
async def toggle_upload_mode(client, callback_query: CallbackQuery):
    """Toggle between document and media upload mode"""
    user_id = callback_query.from_user.id
    
    # Get current mode and toggle it
    current_mode = await codeflixbots.get_upload_mode(user_id)
    new_mode = not current_mode
    
    # Update in database
    await codeflixbots.set_upload_mode(user_id, new_mode)
    
    # Update the settings display
    await refresh_settings_display(client, callback_query)
    
    # Show confirmation
    mode_text = "Document" if new_mode else "Media"
    await callback_query.answer(f"✅ Upload mode changed to: {mode_text}")

@Client.on_callback_query(filters.regex("set_destination"))
async def set_destination(client, callback_query: CallbackQuery):
    """Show destination setup instructions"""
    user_id = callback_query.from_user.id
    bot_username = (await client.get_me()).username
    
    destination_text = f"""📍 **Set Upload Destination**

If you add bot to a channel/group, files will be uploaded there instead of private chat.

**Steps To Add:**
1. First create a new channel or group if you don't have one
2. Click button below to add bot to your channel/group (as Admin with permissions)
3. Send /id command in your channel/group
4. You'll get a chat_id starting with -100
5. Copy and send it here

**For Group Topics:**
Example: -100xxx:topic_id

⏱️ Send Upload Destination ID. Timeout: 60 sec"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏢 Add To Channel", 
                url=f"http://t.me/{bot_username}?startchannel&admin=post_messages+edit_messages+delete_messages"
            ),
            InlineKeyboardButton(
                "👥 Add To Group", 
                url=f"http://t.me/{bot_username}?startgroup&admin=post_messages+edit_messages+delete_messages"
            )
        ],
        [
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_destination")
        ]
    ])
    
    await callback_query.message.edit_text(destination_text, reply_markup=keyboard)
    
    # Set user in waiting state
    waiting_for_destination[user_id] = {
        'message_id': callback_query.message.id,
        'timeout_task': asyncio.create_task(destination_timeout(client, user_id, callback_query.message))
    }

@Client.on_callback_query(filters.regex("cancel_destination"))
async def cancel_destination(client, callback_query: CallbackQuery):
    """Cancel destination setup and return to settings"""
    user_id = callback_query.from_user.id
    
    # Clear waiting state
    if user_id in waiting_for_destination:
        waiting_for_destination[user_id]['timeout_task'].cancel()
        del waiting_for_destination[user_id]
    
    # Return to settings
    await refresh_settings_display(client, callback_query)
    await callback_query.answer("❌ Destination setup cancelled")

@Client.on_message(filters.private & filters.text)
async def handle_destination_input(client, message):
    """Handle destination ID input from user"""
    user_id = message.from_user.id
    
    # Check if user is waiting for destination input
    if user_id not in waiting_for_destination:
        return
    
    chat_id_text = message.text.strip()
    
    # Validate chat ID format
    if not validate_chat_id(chat_id_text):
        await message.reply_text(
            "❌ Invalid chat ID format!\n\n"
            "Please send a valid chat ID starting with -100\n"
            "Example: -100xxxxxxxxx or -100xxx:topic_id"
        )
        return
    
    # Parse chat ID and topic ID
    chat_id, topic_id = parse_chat_id(chat_id_text)
    
    try:
        # Try to get chat info
        chat_info = await client.get_chat(chat_id)
        
        # Check if bot is admin in the chat
        try:
            bot_member = await client.get_chat_member(chat_id, (await client.get_me()).id)
            if bot_member.status not in ["administrator", "creator"]:
                await message.reply_text(
                    "❌ Bot is not an admin in this chat!\n\n"
                    "Please make sure the bot is added as admin with required permissions."
                )
                return
        except Exception:
            await message.reply_text(
                "❌ Bot is not a member of this chat!\n\n"
                "Please add the bot to the channel/group first."
            )
            return
        
        # Save destination info
        destination_data = {
            'chat_id': chat_id,
            'topic_id': topic_id,
            'name': chat_info.title,
            'type': chat_info.type.value
        }
        
        await codeflixbots.set_upload_destination(user_id, destination_data)
        
        # Clear waiting state
        waiting_for_destination[user_id]['timeout_task'].cancel()
        del waiting_for_destination[user_id]
        
        # Success message
        success_text = f"✅ **Destination Set Successfully!**\n\n"
        success_text += f"📍 **Chat:** {chat_info.title}\n"
        success_text += f"🔢 **ID:** `{chat_id_text}`\n"
        if topic_id:
            success_text += f"📋 **Topic ID:** `{topic_id}`\n"
        success_text += f"📱 **Type:** {chat_info.type.value.title()}\n\n"
        success_text += "All future uploads will be sent to this destination."
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 Back to Settings", callback_data="back_to_settings")]
        ])
        
        await message.reply_text(success_text, reply_markup=keyboard)
        
    except PeerIdInvalid:
        await message.reply_text(
            "❌ Invalid chat ID!\n\n"
            "Please check the chat ID and make sure it's correct."
        )
    except Exception as e:
        await message.reply_text(
            f"❌ Error setting destination!\n\n"
            f"Error: {str(e)}\n\n"
            "Please try again or contact support."
        )

@Client.on_callback_query(filters.regex("back_to_settings"))
async def back_to_settings(client, callback_query: CallbackQuery):
    """Return to settings menu"""
    await refresh_settings_display(client, callback_query)

async def refresh_settings_display(client, callback_query: CallbackQuery):
    """Refresh the settings display with current values"""
    user_id = callback_query.from_user.id
    
    # Get current user settings
    upload_as_document = await codeflixbots.get_upload_mode(user_id)
    destination_info = await codeflixbots.get_upload_destination(user_id)
    
    # Format upload mode text
    upload_mode_text = "Send As Document ✅" if upload_as_document else "Send As Media ✅"
    
    # Format destination text
    if destination_info and destination_info.get('chat_id'):
        dest_name = destination_info.get('name', 'Unknown Channel/Group')
        destination_text = f"📍 Destination: {dest_name}"
    else:
        destination_text = "📍 Destination: Private Chat (Default)"
    
    settings_text = f"""🔧 **Bot Settings**

**Current Configuration:**
📤 Upload Mode: {upload_mode_text}
{destination_text}

Choose an option to modify:"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📤 Send As Document" if not upload_as_document else "📤 Send As Media", 
                callback_data="toggle_upload_mode"
            ),
            InlineKeyboardButton("📍 Set Upload Destination", callback_data="set_destination")
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
        ]
    ])
    
    await callback_query.message.edit_text(settings_text, reply_markup=keyboard)

async def destination_timeout(client, user_id, message):
    """Handle timeout for destination input"""
    try:
        await asyncio.sleep(60)  # 60 seconds timeout
        
        if user_id in waiting_for_destination:
            del waiting_for_destination[user_id]
            
            timeout_text = """⏰ **Timeout!**

Destination setup has timed out. Please try again.

/settings - Return to settings"""

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔧 Back to Settings", callback_data="back_to_settings")]
            ])
            
            await message.edit_text(timeout_text, reply_markup=keyboard)
            
    except asyncio.CancelledError:
        pass  # Timeout was cancelled, which is normal

def validate_chat_id(chat_id_text):
    """Validate chat ID format"""
    # Pattern for chat ID with optional topic ID
    pattern = r'^-100\d{10,13}(?::\d+)?$'
    return re.match(pattern, chat_id_text) is not None

def parse_chat_id(chat_id_text):
    """Parse chat ID and topic ID from input"""
    if ':' in chat_id_text:
        chat_id, topic_id = chat_id_text.split(':', 1)
        return int(chat_id), int(topic_id)
    else:
        return int(chat_id_text), None

# Add this to handle the settings button in start_&_cb.py
@Client.on_callback_query(filters.regex("settings"))
async def settings_callback(client, callback_query: CallbackQuery):
    """Handle settings callback from main menu"""
    user_id = callback_query.from_user.id
    
    # Get current user settings
    upload_as_document = await codeflixbots.get_upload_mode(user_id)
    destination_info = await codeflixbots.get_upload_destination(user_id)
    
    # Format upload mode text
    upload_mode_text = "Send As Document ✅" if upload_as_document else "Send As Media ✅"
    
    # Format destination text
    if destination_info and destination_info.get('chat_id'):
        dest_name = destination_info.get('name', 'Unknown Channel/Group')
        destination_text = f"📍 Destination: {dest_name}"
    else:
        destination_text = "📍 Destination: Private Chat (Default)"
    
    settings_text = f"""🔧 **Bot Settings**

**Current Configuration:**
📤 Upload Mode: {upload_mode_text}
{destination_text}

Choose an option to modify:"""

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📤 Send As Document" if not upload_as_document else "📤 Send As Media", 
                callback_data="toggle_upload_mode"
            ),
            InlineKeyboardButton("📍 Set Upload Destination", callback_data="set_destination")
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
        ]
    ])
    
    await callback_query.message.edit_text(settings_text, reply_markup=keyboard)
