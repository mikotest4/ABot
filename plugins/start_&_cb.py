import random
import asyncio
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors import ChatAdminRequired, UserNotParticipant, PeerIdInvalid

from helper.database import codeflixbots
from config import *
from config import Config
from config import Txt

# Store temporary states for users waiting for destination input
waiting_for_destination = {}

# Settings Command Handler
@Client.on_message(filters.private & filters.command("settings"))
async def settings_command(client, message):
    """Main settings command handler"""
    user_id = message.from_user.id
    
    try:
        # Get current user settings with proper error handling
        try:
            upload_as_document = await codeflixbots.get_upload_mode(user_id)
        except:
            upload_as_document = False
            
        try:
            destination_info = await codeflixbots.get_upload_destination(user_id)
        except:
            destination_info = None
        
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
                    callback_data="settings_toggle_upload_mode"
                ),
                InlineKeyboardButton("📍 Set Upload Destination", callback_data="settings_set_destination")
            ],
            [
                InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
            ]
        ])
        
        # Send with image
        settings_image = "https://graph.org/file/255a7bf3992c1bfb4b78a-03d5d005ec6812a81d.jpg"
        
        await message.reply_photo(
            photo=settings_image,
            caption=settings_text,
            reply_markup=keyboard
        )
        
    except Exception as e:
        await message.reply_text(f"❌ Error loading settings: {str(e)}")

# Handle destination ID input from user
@Client.on_message(filters.private & filters.text & ~filters.command([
    'start', 'settings', 'help', 'autorename', 'setmedia', 'metadata', 'queue', 'clearqueue', 
    'queueinfo', 'startsequence', 'endsequence', 'showsequence', 'cancelsequence', 'leaderboard', 
    'settitle', 'setauthor', 'setartist', 'setaudio', 'setsubtitle', 'setvideo', 'set_caption', 
    'del_caption', 'see_caption', 'view_caption', 'view_thumb', 'viewthumb', 'del_thumb', 'delthumb', 
    'tutorial', 'restart', 'stats', 'status', 'broadcast']))
async def handle_destination_input(client, message):
    """Handle destination ID input from user"""
    user_id = message.from_user.id
    
    # Check if user is waiting for destination input
    if user_id not in waiting_for_destination:
        return
    
    try:
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
        
        # Try to get chat info
        try:
            chat_info = await client.get_chat(chat_id)
        except Exception as e:
            await message.reply_text(
                f"❌ Cannot access this chat!\n\n"
                f"Error: {str(e)}\n\n"
                "Please make sure:\n"
                "1. The chat ID is correct\n"
                "2. The bot is added to the chat\n"
                "3. The bot has proper permissions"
            )
            return
        
        # Get bot info
        bot_info = await client.get_me()
        
        # Check if bot is in the chat and has permissions
        try:
            bot_member = await client.get_chat_member(chat_id, bot_info.id)
            
            # Check bot status
            if bot_member.status == "kicked":
                await message.reply_text(
                    "❌ Bot is banned from this chat!\n\n"
                    "Please unban the bot and add it back as admin."
                )
                return
            elif bot_member.status == "left":
                await message.reply_text(
                    "❌ Bot is not in this chat!\n\n"
                    "Please add the bot to the channel/group first."
                )
                return
            elif bot_member.status in ["member"]:
                await message.reply_text(
                    "❌ Bot is only a member, not an admin!\n\n"
                    "Please promote the bot to admin with these permissions:\n"
                    "• Post Messages\n"
                    "• Edit Messages\n"
                    "• Delete Messages"
                )
                return
            elif bot_member.status in ["administrator", "creator"]:
                # Check specific permissions for administrators
                if bot_member.status == "administrator":
                    permissions = bot_member.privileges
                    if permissions:
                        if not permissions.can_post_messages:
                            await message.reply_text(
                                "❌ Bot doesn't have 'Post Messages' permission!\n\n"
                                "Please give the bot permission to post messages."
                            )
                            return
                        if not permissions.can_edit_messages:
                            await message.reply_text(
                                "❌ Bot doesn't have 'Edit Messages' permission!\n\n"
                                "Please give the bot permission to edit messages."
                            )
                            return
                        if not permissions.can_delete_messages:
                            await message.reply_text(
                                "❌ Bot doesn't have 'Delete Messages' permission!\n\n"
                                "Please give the bot permission to delete messages."
                            )
                            return
                
                # Bot has proper admin permissions
                pass
            else:
                await message.reply_text(
                    f"❌ Unknown bot status: {bot_member.status}\n\n"
                    "Please make sure the bot is an admin with proper permissions."
                )
                return
                
        except Exception as e:
            # If we can't get member info, try a different approach
            try:
                # Try to send a test message to verify permissions
                test_msg = await client.send_message(
                    chat_id, 
                    "🤖 **Bot Permission Test**\n\nThis message confirms the bot has proper permissions in this chat.",
                    message_thread_id=topic_id
                )
                # Delete the test message
                await test_msg.delete()
            except Exception as test_error:
                await message.reply_text(
                    f"❌ Bot cannot send messages to this chat!\n\n"
                    f"Error: {str(test_error)}\n\n"
                    "Please make sure:\n"
                    "1. Bot is added to the chat\n"
                    "2. Bot is admin with 'Post Messages' permission\n"
                    "3. Chat allows bots to send messages"
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
        success_text += f"📱 **Type:** {chat_info.type.value.title()}\n"
        success_text += f"👤 **Bot Status:** {bot_member.status.title()}\n\n"
        success_text += "✅ All permissions verified!\n"
        success_text += "All future uploads will be sent to this destination."
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔧 Back to Settings", callback_data="settings_back_to_settings")]
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

# Start Command Handler
@Client.on_message(filters.private & filters.command("start"))
async def start(client, message: Message):
    user = message.from_user
    await codeflixbots.add_user(client, message)

    # Initial interactive text and sticker sequence
    m = await message.reply_text("☎️")
    await asyncio.sleep(0.5)
    await m.edit_text("<code>Dᴇᴠɪʟ ᴍᴀʏ ᴄʀʏ...</code>")
    await asyncio.sleep(0.4)
    await m.edit_text("⚡")
    await asyncio.sleep(0.5)
    await m.edit_text("<code>Jᴀᴄᴋᴘᴏᴛ!!!</code>")
    await asyncio.sleep(0.4)
    await m.delete()

    # Send sticker after the text sequence
    await message.reply_sticker("CAACAgQAAxkBAAIOsGf5RIq9Zodm25_NfFJGKNFNFJv5AALHGAACukfIUwkk20UPuRnvNgQ")

    # Define buttons for the start message
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs •", callback_data='help')
        ],
        
        [
            InlineKeyboardButton("• ᴘʀᴇᴍɪᴜᴍ •", callback_data='premiumx')
        ],
        
        [
            InlineKeyboardButton('• ᴜᴘᴅᴀᴛᴇs', url='https://t.me/+ecWFJBaAGZpjMGY1'),
            InlineKeyboardButton('sᴜᴘᴘᴏʀᴛ •', url='https://t.me/weebs_talk_station')
        ],
        [
            InlineKeyboardButton('• ᴀʙᴏᴜᴛ', callback_data='about')
        ]
    ])

    # Send start message with or without picture
    if Config.START_PIC:
        await message.reply_photo(
            Config.START_PIC,
            caption=Txt.START_TXT.format(user.mention),
            reply_markup=buttons
        )
    else:
        await message.reply_text(
            text=Txt.START_TXT.format(user.mention),
            reply_markup=buttons,
            disable_web_page_preview=True
        )

# Settings callback helper function
async def settings_callback(client, callback_query: CallbackQuery):
    """Handle settings callback from main menu"""
    user_id = callback_query.from_user.id
    
    try:
        # Get current user settings with proper error handling
        try:
            upload_as_document = await codeflixbots.get_upload_mode(user_id)
        except:
            upload_as_document = False
            
        try:
            destination_info = await codeflixbots.get_upload_destination(user_id)
        except:
            destination_info = None
        
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
                    callback_data="settings_toggle_upload_mode"
                ),
                InlineKeyboardButton("📍 Set Upload Destination", callback_data="settings_set_destination")
            ],
            [
                InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
            ]
        ])
        
        # Send with image
        settings_image = "https://graph.org/file/255a7bf3992c1bfb4b78a-03d5d005ec6812a81d.jpg"
        
        # Check if we can edit with media or need to send new message
        try:
            # pyrogram expects InputMediaPhoto for edit_media, create accordingly
            from pyrogram.types import InputMediaPhoto
            media = InputMediaPhoto(settings_image)
            await callback_query.message.edit_media(
                media=media,
                caption=settings_text,
                reply_markup=keyboard
            )
        except:
            # If editing media fails, delete old message and send new one
            try:
                await callback_query.message.delete()
            except:
                pass
            await callback_query.message.reply_photo(
                photo=settings_image,
                caption=settings_text,
                reply_markup=keyboard
            )
        
    except Exception as e:
        await callback_query.answer(f"❌ Error loading settings: {str(e)}")

# Callback Query Handler
@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    print(f"Callback data received: {data}")  # Debugging line

    # Handle settings-related callbacks first
    if data.startswith("settings_"):
        if data == "settings_toggle_upload_mode":
            try:
                # Get current mode and toggle it
                try:
                    current_mode = await codeflixbots.get_upload_mode(user_id)
                except:
                    current_mode = False
                    
                new_mode = not current_mode
                
                # Update in database
                try:
                    await codeflixbots.set_upload_mode(user_id, new_mode)
                except Exception as e:
                    await query.answer(f"❌ Database error: {str(e)}")
                    return
                
                # Update the settings display
                await settings_callback(client, query)
                
                # Show confirmation
                mode_text = "Document" if new_mode else "Media"
                await query.answer(f"✅ Upload mode changed to: {mode_text}")
                
            except Exception as e:
                await query.answer(f"❌ Error: {str(e)}")
                
        elif data == "settings_set_destination":
            try:
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
                        InlineKeyboardButton("❌ Cancel", callback_data="settings_cancel_destination")
                    ]
                ])
                
                # Use same settings image for destination page
                settings_image = "https://graph.org/file/255a7bf3992c1bfb4b78a-03d5d005ec6812a81d.jpg"
                
                try:
                    # Use InputMediaPhoto here as well
                    from pyrogram.types import InputMediaPhoto
                    media = InputMediaPhoto(settings_image)
                    await query.message.edit_media(
                        media=media,
                        caption=destination_text,
                        reply_markup=keyboard
                    )
                except:
                    try:
                        await query.message.edit_caption(
                            caption=destination_text,
                            reply_markup=keyboard
                        )
                    except:
                        await query.message.edit_text(
                            text=destination_text,
                            reply_markup=keyboard
                        )
                
                # Set user in waiting state
                waiting_for_destination[user_id] = {
                    'message_id': query.message.id,
                    'timeout_task': asyncio.create_task(destination_timeout(client, user_id, query.message))
                }
                
                await query.answer("📍 Follow the steps to set destination")
                
            except Exception as e:
                await query.answer(f"❌ Error: {str(e)}")
                
        elif data == "settings_cancel_destination":
            # Clear waiting state
            if user_id in waiting_for_destination:
                waiting_for_destination[user_id]['timeout_task'].cancel()
                del waiting_for_destination[user_id]
            
            await settings_callback(client, query)
            await query.answer("❌ Destination setup cancelled")
            
        elif data == "settings_back_to_settings":
            await settings_callback(client, query)
            
        return  # Exit early for settings callbacks

    # Handle regular callbacks
    if data == "home":
        await query.message.edit_text(
            text=Txt.START_TXT.format(query.from_user.mention),
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs •", callback_data='help')],
                [InlineKeyboardButton("• ᴘʀᴇᴍɪᴜᴍ •", callback_data='premiumx')],
                [InlineKeyboardButton('• ᴜᴘᴅᴀᴛᴇs', url='https://t.me/+ecWFJBaAGZpjMGY1'), InlineKeyboardButton('sᴜᴘᴘᴏʀᴛ •', url='https://t.me/weebs_talk_station')],
                [InlineKeyboardButton('• ᴀʙᴏᴜᴛ', callback_data='about')]
            ])
        )
    elif data == "caption":
        await query.message.edit_text(
            text=Txt.CAPTION_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/weebs_talk_station'), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
            ])
        )

    elif data == "help":
        await query.message.edit_text(
            text=Txt.HELP_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ғᴏʀᴍᴀᴛ •", callback_data='file_names')],
                [InlineKeyboardButton("• sᴇǫᴜᴇɴᴄᴇ ғɪʟᴇs •", callback_data='sequence_help')],
                [InlineKeyboardButton('• ᴛʜᴜᴍʙɴᴀɪʟ', callback_data='thumbnail'), InlineKeyboardButton('ᴄᴀᴘᴛɪᴏɴ •', callback_data='caption')],
                [InlineKeyboardButton('• ᴍᴇᴛᴀᴅᴀᴛᴀ', callback_data='meta'), InlineKeyboardButton('ᴅᴏɴᴀᴛᴇ •', callback_data='donate')],
                [InlineKeyboardButton('• sᴇᴛᴛɪɴɢs', callback_data='settings_main')],
                [InlineKeyboardButton('• ʜᴏᴍᴇ', callback_data='home')]
            ])
        )

    elif data == "settings_main":
        await settings_callback(client, query)

    elif data == "sequence_help":
        await query.message.edit_text(
            text=Txt.SEQUENCE_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
            ])
        )

    elif data == "meta":
        await query.message.edit_text(
            text=Txt.SEND_METADATA,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
            ])
        )
    elif data == "donate":
        await query.message.edit_text(
            text=Txt.DONATE_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="help"), InlineKeyboardButton("ᴏᴡɴᴇʀ •", url='https://t.me/IntrovertSama')]
            ])
        )
    elif data == "file_names":
        format_template = await codeflixbots.get_format_template(user_id)
        await query.message.edit_text(
            text=Txt.FILE_NAME_TXT.format(format_template=format_template),
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/weebs_talk_station'), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
            ])
        )
    elif data == "thumbnail":
        await query.message.edit_text(
            text=Txt.THUMBNAIL_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/weebs_talk_station'), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
            ])
        )
    elif data == "about":
        await query.message.edit_text(
            text=Txt.ABOUT_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/weebs_talk_station'), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="home")]
            ])
        )
    elif data == "premiumx":
        await query.message.edit_text(
            text=Txt.PREMIUM_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ", callback_data="plans"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="home")]
            ])
        )
    elif data == "plans":
        await query.message.edit_text(
            text=Txt.PLANS_TXT,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="premiumx"), InlineKeyboardButton("ᴏᴡɴᴇʀ •", url='https://t.me/IntrovertSama')]
            ])
        )
    elif data == "close":
        await query.message.delete()
        try:
            await query.message.reply_to_message.delete()
        except:
            pass

# Helper functions
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
                [InlineKeyboardButton("🔧 Back to Settings", callback_data="settings_back_to_settings")]
            ])
            
            await message.edit_text(timeout_text, reply_markup=keyboard)
            
    except asyncio.CancelledError:
        pass  # Timeout was cancelled, which is normal
    except Exception as e:
        print(f"Error in destination timeout: {e}")

def validate_chat_id(chat_id_text):
    """Validate chat ID format"""
    # Pattern for chat ID with optional topic ID (after colon)
    pattern = r'^-100\d{10,13}(?::\d+)?$'
    return re.match(pattern, chat_id_text) is not None

def parse_chat_id(chat_id_text):
    """Parse chat ID and topic ID from input"""
    if ':' in chat_id_text:
        chat_id_str, topic_id_str = chat_id_text.split(':', 1)
        return int(chat_id_str), int(topic_id_str)
    else:
        return int(chat_id_text), None
