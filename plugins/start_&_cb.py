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

# Settings callback helper function
async def settings_callback(client, callback_query: CallbackQuery):
    """Handle settings callback from main menu"""
    user_id = callback_query.from_user.id
    
    try:
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
                    callback_data="settings_toggle_upload_mode"
                ),
                InlineKeyboardButton("📍 Set Upload Destination", callback_data="settings_set_destination")
            ],
            [
                InlineKeyboardButton("🔙 Back to Menu", callback_data="home")
            ]
        ])
        
        await callback_query.message.edit_text(settings_text, reply_markup=keyboard)
        
    except Exception as e:
        await callback_query.answer(f"❌ Error loading settings: {str(e)}")

# Callback Query Handler
@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    print(f"Callback data received: {data}")  # Debugging line

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
