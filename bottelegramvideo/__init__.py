# Bot Telegram para Download de Vídeos
# Versão modularizada

__version__ = "2.0.0"
__author__ = "Bot Telegram Video Downloader"

# Importações principais
from .utils import (
    create_progress_bar,
    get_loading_emoji,
    get_status_emoji,
    send_progress_message,
    is_good_quality_image,
    is_story_url,
    parse_time_to_seconds,
    format_seconds_to_time,
    cleanup_temp_files,
    force_cleanup_temp_files,
    check_ffmpeg
)

from .queue_manager import (
    QueueItem,
    download_queue,
    queue_lock,
    current_download,
    load_queue,
    save_queue,
    add_to_queue,
    remove_from_queue,
    get_next_queue_item,
    is_queue_processing,
    clear_user_queue,
    clear_completed_items,
    get_user_queue_stats,
    get_queue_position
)

from .downloaders import (
    split_video_with_ytdlp,
    split_file_by_size,
    download_story,
    send_video_with_fallback,
    list_available_videos,
    get_video_qualities
)

__all__ = [
    # Utils
    'create_progress_bar',
    'get_loading_emoji', 
    'get_status_emoji',
    'send_progress_message',
    'is_good_quality_image',
    'is_story_url',
    'parse_time_to_seconds',
    'format_seconds_to_time',
    'cleanup_temp_files',
    'force_cleanup_temp_files',
    'check_ffmpeg',
    
    # Queue Manager
    'QueueItem',
    'download_queue',
    'queue_lock',
    'current_download',
    'load_queue',
    'save_queue',
    'add_to_queue',
    'remove_from_queue',
    'get_next_queue_item',
    'is_queue_processing',
    'clear_user_queue',
    'clear_completed_items',
    'get_user_queue_stats',
    'get_queue_position',
    
    # Downloaders
    'split_video_with_ytdlp',
    'split_file_by_size',
    'download_story',
    'send_video_with_fallback',
    'list_available_videos',
    'get_video_qualities'
]