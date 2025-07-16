import random
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from helper.database import codeflixbots
from config import *
from config import Config
from config import Txt

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
            #InlineKeyboardButton('sᴏᴜʀᴄᴇ •', callback_data='source')
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

# Settings Command Handler
@Client.on_message(filters.private & filters.command("settings"))
async def settings_command(client, message):
    # Just call the settings callback helper with a dummy callback_query-like object
    class DummyCallback:
        def __init__(self, message, from_user):
            self.message = message
            self.from_user = from_user
            self.id = from_user.id
        async def answer(self, text):  # dummy answer method
            await message.reply_text(text)
    dummy_callback = DummyCallback(message, message.from_user)
    await settings_callback(client, dummy_callback)

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
            # edit_media expects an InputMediaPhoto or similar, so importing InputMediaPhoto
            from pyrogram.types import InputMediaPhoto
            await callback_query.message.edit_media(
                media=InputMediaPhoto(settings_image),
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
                    from pyrogram.types import InputMediaPhoto
                    await query.message.edit_media(
                        media=InputMediaPhoto(settings_image),
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
                
                await query.answer("📍 Follow the steps to set destination")
                
            except Exception as e:
                await query.answer(f"❌ Error: {str(e)}")
                
        elif data == "settings_cancel_destination":
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
                [InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="help"), InlineKeyboardButton("ᴏᴡɴᴇʀ •", callback_data='https://t.me/IntrovertSama')]
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
