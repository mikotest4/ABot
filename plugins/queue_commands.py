import asyncio
import time
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from plugins.file_rename import processing_stats, user_queues, active_tasks, MAX_CONCURRENT_PER_USER
from helper.utils import humanbytes
from config import Config

@Client.on_message(filters.private & filters.command("queue"))
async def show_queue_status(client, message):
    """Show detailed queue status for the user"""
    user_id = message.from_user.id
    
    if user_id not in processing_stats:
        await message.reply_text(
            "📋 **No files in processing queue**\n\n"
            "Send some files to start processing!"
        )
        return
    
    stats = processing_stats[user_id]
    active = stats["active"]
    queued = stats["queued"]
    
    # Calculate estimated wait time
    avg_processing_time = 120  # 2 minutes average per file
    estimated_wait = queued * avg_processing_time
    wait_time = str(timedelta(seconds=estimated_wait))
    
    # Get queue details if files are queued
    queue_details = ""
    if user_id in user_queues and user_queues[user_id]:
        queue_details = "\n**📂 Files in Queue:**\n"
        for i, file_task in enumerate(list(user_queues[user_id])[:5], 1):
            file_size = humanbytes(file_task.file_size)
            queue_details += f"{i}. `{file_task.original_filename}` ({file_size})\n"
        
        if len(user_queues[user_id]) > 5:
            remaining = len(user_queues[user_id]) - 5
            queue_details += f"... and {remaining} more files\n"
    
    # Get active tasks details
    active_details = ""
    if user_id in active_tasks and active_tasks[user_id]:
        active_details = "\n**🔄 Currently Processing:**\n"
        for i, task_id in enumerate(list(active_tasks[user_id].keys())[:3], 1):
            active_details += f"Slot {i}: Processing...\n"
    
    status_text = f"""📋 **Your Queue Status**

🔄 **Currently Processing**: {active}/{MAX_CONCURRENT_PER_USER} slots
⏳ **Files in Queue**: {queued}
⚡ **Total Capacity**: {MAX_CONCURRENT_PER_USER} files simultaneously
⏱️ **Estimated Wait**: {wait_time if queued > 0 else 'No wait'}

{active_details}{queue_details}

{'🟢 **Ready to accept more files!**' if active < MAX_CONCURRENT_PER_USER else '🔴 **All slots busy** - new files will be queued'}
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_queue"),
            InlineKeyboardButton("🗑️ Clear Queue", callback_data="clear_queue_confirm")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_queue_status")
        ]
    ])
    
    await message.reply_text(status_text, reply_markup=keyboard)

@Client.on_message(filters.private & filters.command("clearqueue"))
async def clear_queue_command(client, message):
    """Clear all pending files from queue"""
    user_id = message.from_user.id
    
    if user_id not in user_queues or not user_queues[user_id]:
        await message.reply_text("📋 **No files in queue to clear**")
        return
    
    # Show confirmation
    queued_count = len(user_queues[user_id])
    active_count = processing_stats[user_id]["active"] if user_id in processing_stats else 0
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Clear All", callback_data="confirm_clear_queue"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear_queue")
        ]
    ])
    
    await message.reply_text(
        f"⚠️ **Confirm Queue Clear**\n\n"
        f"📂 **Files to be cleared**: {queued_count}\n"
        f"🔄 **Currently processing**: {active_count} (will continue)\n\n"
        f"Are you sure you want to clear all queued files?",
        reply_markup=keyboard
    )

@Client.on_message(filters.private & filters.command("queueinfo"))
async def queue_system_info(client, message):
    """Show information about the queue system"""
    
    info_text = f"""📋 **Queue System Information**

**🔧 How it works:**
• Bot can process up to **{MAX_CONCURRENT_PER_USER} files simultaneously**
• Additional files are automatically **queued**
• Files are processed in **first-come, first-served** order
• You get **real-time status updates** for each file

**📊 Queue Features:**
• **Concurrent Processing**: Multiple files at once
• **Smart Queueing**: No file loss, automatic management
• **Progress Tracking**: Real-time updates per slot
• **Error Handling**: Failed files don't affect others
• **Resource Management**: Efficient memory and storage use

**🎯 Commands:**
• `/queue` - Check your current queue status
• `/clearqueue` - Clear all pending files from queue
• `/queueinfo` - Show this information

**💡 Tips:**
• Send multiple files at once - they'll be queued automatically
• Each file shows its processing slot (1/{MAX_CONCURRENT_PER_USER}, 2/{MAX_CONCURRENT_PER_USER}, etc.)
• Queue position updates in real-time
• Processing continues even if you go offline

**⚡ Performance:**
• Average processing time: ~2-3 minutes per file
• Depends on file size and metadata complexity
• Network speed affects upload/download times
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Check My Queue", callback_data="check_my_queue"),
            InlineKeyboardButton("❌ Close", callback_data="close_info")
        ]
    ])
    
    await message.reply_text(info_text, reply_markup=keyboard)

@Client.on_message(filters.private & filters.command("queuestats"))
async def queue_statistics(client, message):
    """Show overall queue statistics (admin only)"""
    user_id = message.from_user.id
    
    # Check if user is admin
    if user_id not in Config.ADMIN:
        await message.reply_text("❌ **Admin only command**")
        return
    
    # Calculate global statistics
    total_users_with_queues = len([uid for uid in processing_stats.keys()])
    total_active_files = sum([stats["active"] for stats in processing_stats.values()])
    total_queued_files = sum([stats["queued"] for stats in processing_stats.values()])
    total_capacity = total_users_with_queues * MAX_CONCURRENT_PER_USER
    
    # Get top users by queue size
    top_users = sorted(
        [(uid, stats["queued"] + stats["active"]) for uid, stats in processing_stats.items()],
        key=lambda x: x[1], reverse=True
    )[:5]
    
    top_users_text = ""
    for i, (uid, total_files) in enumerate(top_users, 1):
        if total_files > 0:
            try:
                user = await client.get_users(uid)
                username = user.first_name or "Unknown"
            except:
                username = f"User {uid}"
            top_users_text += f"{i}. {username}: {total_files} files\n"
    
    stats_text = f"""📊 **Global Queue Statistics**

**📈 Current Status:**
• **Active Users**: {total_users_with_queues}
• **Files Processing**: {total_active_files}
• **Files Queued**: {total_queued_files}
• **Total Capacity**: {total_capacity} slots
• **Utilization**: {(total_active_files/total_capacity*100):.1f}% if total_capacity > 0 else 0%

**👥 Top Users by File Count:**
{top_users_text if top_users_text else "No active users"}

**⚙️ System Settings:**
• **Max Concurrent per User**: {MAX_CONCURRENT_PER_USER}
• **Queue Timeout**: {Config.QUEUE_TIMEOUT} seconds
• **Auto Cleanup**: Enabled

**💾 Memory Usage:**
• **Active Tasks**: {len([task for tasks in active_tasks.values() for task in tasks.values()])}
• **Queue Objects**: {len([queue for queue in user_queues.values()])}
    """
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_admin_stats"),
            InlineKeyboardButton("❌ Close", callback_data="close_admin_stats")
        ]
    ])
    
    await message.reply_text(stats_text, reply_markup=keyboard)

# Callback handlers for inline buttons
@Client.on_callback_query(filters.regex(r"^(refresh_queue|clear_queue_confirm|close_queue_status)$"))
async def queue_callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "refresh_queue":
        # Refresh queue status
        await callback_query.answer("🔄 Refreshing...")
        
        if user_id not in processing_stats:
            await callback_query.message.edit_text("📋 **No files in processing queue**")
            return
        
        stats = processing_stats[user_id]
        active = stats["active"]
        queued = stats["queued"]
        
        estimated_wait = queued * 120  # 2 minutes average
        wait_time = str(timedelta(seconds=estimated_wait))
        
        status_text = f"""📋 **Your Queue Status** *(Updated: {datetime.now().strftime('%H:%M:%S')})*

🔄 **Currently Processing**: {active}/{MAX_CONCURRENT_PER_USER} slots
⏳ **Files in Queue**: {queued}
⏱️ **Estimated Wait**: {wait_time if queued > 0 else 'No wait'}

{'🟢 **Ready to accept more files!**' if active < MAX_CONCURRENT_PER_USER else '🔴 **All slots busy** - new files will be queued'}
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="refresh_queue"),
                InlineKeyboardButton("🗑️ Clear Queue", callback_data="clear_queue_confirm")
            ],
            [
                InlineKeyboardButton("❌ Close", callback_data="close_queue_status")
            ]
        ])
        
        await callback_query.message.edit_text(status_text, reply_markup=keyboard)
        
    elif data == "clear_queue_confirm":
        # Show clear confirmation
        await callback_query.answer()
        
        if user_id not in user_queues or not user_queues[user_id]:
            await callback_query.message.edit_text("📋 **No files in queue to clear**")
            return
        
        queued_count = len(user_queues[user_id])
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Clear All", callback_data="confirm_clear_queue"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_clear_queue")
            ]
        ])
        
        await callback_query.message.edit_text(
            f"⚠️ **Confirm Queue Clear**\n\n"
            f"📂 **Files to be cleared**: {queued_count}\n\n"
            f"Are you sure you want to clear all queued files?",
            reply_markup=keyboard
        )
        
    elif data == "close_queue_status":
        await callback_query.answer()
        await callback_query.message.delete()

@Client.on_callback_query(filters.regex(r"^(confirm_clear_queue|cancel_clear_queue)$"))
async def clear_queue_callback(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "confirm_clear_queue":
        await callback_query.answer("🗑️ Clearing queue...")
        
        if user_id in user_queues:
            queued_count = len(user_queues[user_id])
            user_queues[user_id].clear()
            processing_stats[user_id]["queued"] = 0
            
            await callback_query.message.edit_text(
                f"✅ **Queue Cleared Successfully**\n\n"
                f"🗑️ **Removed {queued_count} files** from queue\n"
                f"🔄 **Currently processing files** will continue normally"
            )
        else:
            await callback_query.message.edit_text("📋 **No files were in queue**")
            
    elif data == "cancel_clear_queue":
        await callback_query.answer("❌ Cancelled")
        await callback_query.message.edit_text("❌ **Queue clear cancelled**")

@Client.on_callback_query(filters.regex(r"^(check_my_queue|close_info)$"))
async def info_callback_handler(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "check_my_queue":
        await callback_query.answer("📋 Checking your queue...")
        
        if user_id not in processing_stats:
            await callback_query.message.edit_text("📋 **No files in processing queue**")
            return
        
        stats = processing_stats[user_id]
        active = stats["active"]
        queued = stats["queued"]
        
        status_text = f"""📋 **Your Current Queue Status**

🔄 **Processing**: {active}/{MAX_CONCURRENT_PER_USER} slots
⏳ **Queued**: {queued} files
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Detailed View", callback_data="refresh_queue"),
                InlineKeyboardButton("❌ Close", callback_data="close_info")
            ]
        ])
        
        await callback_query.message.edit_text(status_text, reply_markup=keyboard)
        
    elif data == "close_info":
        await callback_query.answer()
        await callback_query.message.delete()

@Client.on_callback_query(filters.regex(r"^(refresh_admin_stats|close_admin_stats)$"))
async def admin_stats_callback(client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    # Check admin permission
    if user_id not in Config.ADMIN:
        await callback_query.answer("❌ Admin only", show_alert=True)
        return
    
    if data == "refresh_admin_stats":
        await callback_query.answer("🔄 Refreshing admin stats...")
        
        # Recalculate statistics
        total_users_with_queues = len([uid for uid in processing_stats.keys()])
        total_active_files = sum([stats["active"] for stats in processing_stats.values()])
        total_queued_files = sum([stats["queued"] for stats in processing_stats.values()])
        total_capacity = total_users_with_queues * MAX_CONCURRENT_PER_USER
        
        stats_text = f"""📊 **Global Queue Statistics** *(Updated: {datetime.now().strftime('%H:%M:%S')})*

**📈 Current Status:**
• **Active Users**: {total_users_with_queues}
• **Files Processing**: {total_active_files}
• **Files Queued**: {total_queued_files}
• **Total Capacity**: {total_capacity} slots
• **Utilization**: {(total_active_files/total_capacity*100):.1f}% if total_capacity > 0 else 0%

**⚙️ System Settings:**
• **Max Concurrent per User**: {MAX_CONCURRENT_PER_USER}
• **Queue Timeout**: {Config.QUEUE_TIMEOUT} seconds
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="refresh_admin_stats"),
                InlineKeyboardButton("❌ Close", callback_data="close_admin_stats")
            ]
        ])
        
        await callback_query.message.edit_text(stats_text, reply_markup=keyboard)
        
    elif data == "close_admin_stats":
        await callback_query.answer()
        await callback_query.message.delete()
