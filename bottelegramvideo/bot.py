import logging
import os
import subprocess
import asyncio
import json
import glob
import time
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ChatAction

# Importa módulos locais
from utils import (
    create_progress_bar, get_loading_emoji, send_progress_message,
    is_good_quality_image, is_story_url, parse_time_to_seconds,
    format_seconds_to_time, cleanup_temp_files, force_cleanup_temp_files
)
from queue_manager import (
    download_queue, current_download, add_to_queue, get_next_queue_item,
    is_queue_processing, clear_user_queue, clear_completed_items,
    get_user_queue_stats, save_queue
)
from downloaders import (
    download_story, send_video_with_fallback, list_available_videos,
    get_video_qualities, split_file_by_size
)

# Importa novos downloaders específicos
from tiktok_downloader import (
    download_tiktok_video, download_tiktok_audio, is_tiktok_url
)
from twitter_downloader import (
    download_twitter_video, download_twitter_gif, is_twitter_url
)
from youtube_shorts_downloader import (
    download_youtube_short, is_youtube_shorts_url, is_vertical_youtube_video
)
from twitch_downloader import (
    download_twitch_clip, is_twitch_url, is_twitch_clip_url
)
from pinterest_downloader import (
    download_pinterest_pin, is_pinterest_url
)
from linkedin_downloader import (
    download_linkedin_video, is_linkedin_url, get_linkedin_content_type
)
from telegram_downloader import (
    download_telegram_channel, download_telegram_message, is_telegram_url,
    is_telegram_channel_url, is_telegram_message_url
)
from watermark_processor import (
    apply_text_watermark, apply_logo_watermark, watermark_processor
)

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Configura o logging para debug
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Envia uma mensagem de boas-vindas com menu de botões."""
    user = update.effective_user
    
    # Cria menu principal com botões
    keyboard = [
        [
            InlineKeyboardButton("📋 Ver Fila", callback_data="menu_queue"),
            InlineKeyboardButton("🧹 Limpar Arquivos", callback_data="menu_cleanup")
        ],
        [
            InlineKeyboardButton("✂️ Cortar Vídeo", callback_data="menu_cut"),
            InlineKeyboardButton("📱 Download Story", callback_data="menu_story")
        ],
        [
            InlineKeyboardButton("🖼️ Download Imagens", callback_data="menu_images"),
            InlineKeyboardButton("❓ Ajuda", callback_data="menu_help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_html(
        f"🤖 **Olá, {user.mention_html()}!**\n\n" +
        "📱 **Como usar:**\n" +
        "• Envie um link diretamente no chat\n" +
        "• Ou use os botões abaixo para funções específicas\n\n" +
        "🎬 **Plataformas suportadas:**\n" +
        "YouTube, TikTok, Instagram, Facebook e muito mais!\n\n" +
        "👇 **Escolha uma opção:**",
        reply_markup=reply_markup
    )

# Função para o comando /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra a lista de comandos disponíveis."""
    help_text = (
        "🤖 **Como usar o bot:**\n\n"
        "🔗 **Modo principal (Recomendado):**\n"
        "Envie qualquer link de vídeo ou imagem e escolha o que baixar\n\n"
        "🎬 **Download de vídeos:**\n"
        "• Suporte a múltiplas qualidades\n"
        "• Divisão automática para arquivos grandes\n\n"
        "🖼️ **Download de imagens:**\n"
        "• Todas as imagens disponíveis\n"
        "• Filtro automático de qualidade\n\n"
        "📋 **Comandos disponíveis:**\n"
        "• `/start` - Mensagem de boas-vindas\n"
        "• `/help` - Esta mensagem de ajuda\n"
        "• `/images [URL]` - Download direto de imagens\n"
        "• `/queue` - Ver fila de downloads\n"
        "• `/clear_queue` - Limpar fila de downloads\n"
        "• `/cut [URL] [início] [fim]` - Cortar vídeo por tempo\n"
        "• `/story [URL]` - Download de Stories (Instagram/Facebook)\n"
        "• `/watermark` - Ativar modo marca d'água\n"
        "• `/cleanup` - Limpar arquivos temporários\n"
        "• `/priority` - Adicionar download com prioridade alta"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Função para mostrar a fila de downloads
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra a fila de downloads atual."""
    chat_id = update.message.chat_id
    
    stats, user_items = get_user_queue_stats(chat_id)
    
    if stats['total'] == 0:
        await update.message.reply_text("📭 **Fila de downloads vazia**\n\nNenhum download na fila no momento.", parse_mode='Markdown')
        return
    
    # Cabeçalho com estatísticas visuais
    queue_text = f"📋 **Sua Fila de Downloads**\n\n"
    queue_text += f"📊 **Estatísticas:**\n"
    queue_text += f"⏳ Pendentes: {stats['pending']}\n"
    queue_text += f"⬇️ Baixando: {stats['downloading']}\n"
    queue_text += f"✅ Concluídos: {stats['completed']}\n"
    queue_text += f"❌ Falharam: {stats['failed']}\n\n"
    
    if stats['pending'] > 0 or stats['downloading'] > 0:
        progress_percentage = (stats['completed'] / stats['total']) * 100
        progress_bar = create_progress_bar(int(progress_percentage))
        queue_text += f"📈 **Progresso Geral:**\n{progress_bar}\n\n"
    
    queue_text += "📝 **Itens na Fila:**\n\n"
    
    for i, item in enumerate(user_items[:10], 1):  # Mostra até 10 itens
        # Emojis mais informativos
        status_emoji = {
            'pending': '⏳',
            'downloading': get_loading_emoji(i),  # Emoji animado
            'completed': '✅',
            'failed': '❌'
        }.get(item.status, '❓')
        
        priority_emoji = {
            'high': '🔥',
            'normal': '📋',
            'low': '🔽'
        }.get(item.priority, '📋')
        
        type_emoji = {
            'video': '🎬',
            'images': '🖼️',
            'audio': '🎵',
            'video_cut': '✂️'
        }.get(item.download_type, '📁')
        
        url_short = item.url[:35] + "..." if len(item.url) > 35 else item.url
        
        # Adiciona tempo estimado para itens pendentes
        time_info = ""
        if item.status == 'downloading' and item.started_time:
            start_time = datetime.fromisoformat(item.started_time)
            elapsed = datetime.now() - start_time
            time_info = f" ({elapsed.seconds}s)"
        elif item.status == 'completed' and item.completed_time:
            time_info = " ✨"
        
        queue_text += f"{i}. {status_emoji} {priority_emoji} {type_emoji} `{url_short}`{time_info}\n"
        
        if item.status == 'failed' and item.error_message:
            queue_text += f"   ❌ Erro: {item.error_message[:50]}...\n"
    
    if len(user_items) > 10:
        queue_text += f"\n... e mais {len(user_items) - 10} itens\n"
    
    # Adiciona informações sobre processamento
    if current_download:
        queue_text += f"\n🔄 **Processando:** {current_download.download_type}\n"
    
    # Cria botões para gerenciar a fila
    keyboard = [
        [
            InlineKeyboardButton("🔄 Atualizar", callback_data="queue_refresh"),
            InlineKeyboardButton("🗑️ Limpar Concluídos", callback_data="queue_clear_completed")
        ],
        [
            InlineKeyboardButton("❌ Limpar Tudo", callback_data="queue_clear_all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(queue_text, reply_markup=reply_markup, parse_mode='Markdown')

# Função para limpar a fila
async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Limpa a fila de downloads do usuário."""
    chat_id = update.message.chat_id
    
    removed_count = await clear_user_queue(chat_id)
    
    if removed_count > 0:
        await send_progress_message(
            context, chat_id,
            f"Fila limpa\n\n{removed_count} itens removidos",
            'completed'
        )
    else:
        await send_progress_message(
            context, chat_id,
            "Fila já estava vazia",
            'info'
        )

# Função para limpeza de arquivos
async def cleanup_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Limpa arquivos temporários."""
    chat_id = update.message.chat_id
    
    await send_progress_message(context, chat_id, "Limpando arquivos temporários", 'processing')
    
    try:
        removed_count = force_cleanup_temp_files()
        
        if removed_count > 0:
            await send_progress_message(
                context, chat_id,
                f"Limpeza concluída\n\n{removed_count} arquivos removidos",
                'completed'
            )
        else:
            await send_progress_message(
                context, chat_id,
                "Nenhum arquivo temporário encontrado",
                'info'
            )
    except Exception as e:
        logger.error(f"Erro no comando de limpeza: {e}")
        await send_progress_message(
            context, chat_id,
            f"Erro na limpeza\n\nDetalhes: {str(e)[:50]}...",
            'error'
        )

# Função para cortar vídeo
async def cut_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Corta um vídeo entre os tempos especificados."""
    chat_id = update.message.chat_id
    
    if len(context.args) < 3:
        await send_progress_message(
            context, chat_id,
            "Uso correto: /cut [URL] [início] [fim]\n\nExemplo: /cut https://youtube.com/watch?v=abc 00:30 01:45",
            'info'
        )
        return
    
    try:
        url = context.args[0]
        start_time = context.args[1]
        end_time = context.args[2]
        
        # Valida os tempos
        start_seconds = parse_time_to_seconds(start_time)
        end_seconds = parse_time_to_seconds(end_time)
        
        if start_seconds >= end_seconds:
            await send_progress_message(
                context, chat_id,
                "Tempo de início deve ser menor que o tempo final",
                'error'
            )
            return
        
        duration = end_seconds - start_seconds
        
        # Armazena URL no contexto
        if 'user_urls' not in context.user_data:
            context.user_data['user_urls'] = {}
        
        url_id = f"{chat_id}_{update.message.message_id}"
        context.user_data['user_urls'][url_id] = url
        
        # Cria botões para opções de corte
        keyboard = [
            [
                InlineKeyboardButton("✂️ Cortar Agora", callback_data=f"cut_now:{start_time}:{end_time}:{url_id}"),
                InlineKeyboardButton("📋 Adicionar à Fila", callback_data=f"cut_queue:{start_time}:{end_time}:{url_id}")
            ],
            [
                InlineKeyboardButton("🎬 Ver Qualidades", callback_data=f"cut_quality:{start_time}:{end_time}:{url_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✂️ **Corte de Vídeo Configurado**\n\n"
            f"📎 **URL:** `{url[:50]}...`\n"
            f"⏰ **Início:** {start_time} ({start_seconds}s)\n"
            f"⏰ **Fim:** {end_time} ({end_seconds}s)\n"
            f"⏱️ **Duração:** {format_seconds_to_time(duration)}\n\n"
            f"Escolha uma opção:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except ValueError as e:
        await send_progress_message(
            context, chat_id,
            f"Erro no formato de tempo\n\nDetalhes: {str(e)}",
            'error'
        )
    except Exception as e:
        await send_progress_message(
            context, chat_id,
            f"Erro inesperado\n\nDetalhes: {str(e)[:50]}...",
            'error'
        )

# Função para download de imagens
async def download_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Baixa imagens do link fornecido."""
    chat_id = update.message.chat_id
    
    if not context.args:
        await send_progress_message(
            context, chat_id,
            "Uso correto: /images [URL]\n\nExemplo: /images https://instagram.com/p/abc123",
            'info'
        )
        return
    
    url = context.args[0]
    await send_progress_message(context, chat_id, "Procurando imagens", 'starting')
    
    # Adiciona à fila
    user_name = update.effective_user.first_name or "Usuário"
    await add_to_queue(chat_id, url, 'images', user_name)
    
    await send_progress_message(
        context, chat_id,
        "Imagens adicionadas à fila\n\n💡 Use /queue para acompanhar",
        'info'
    )
    
    # Inicia processamento se não estiver rodando
    if not is_queue_processing():
        asyncio.create_task(process_download_queue(context))

# Função para marca d'água
async def watermark_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ativa o modo marca d'água para a próxima imagem enviada."""
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    
    # Armazena o estado do usuário
    if 'watermark_mode' not in context.user_data:
        context.user_data['watermark_mode'] = {}
    
    context.user_data['watermark_mode'][user_id] = {
        'active': True,
        'text': context.args[0] if context.args else None,
        'position': 'bottom_right',
        'opacity': 0.7
    }
    
    # Cria teclado com opções
    keyboard = [
        [
            InlineKeyboardButton("📝 Personalizar Texto", callback_data=f"wm_text:{user_id}"),
            InlineKeyboardButton("📍 Mudar Posição", callback_data=f"wm_position:{user_id}")
        ],
        [
            InlineKeyboardButton("🎨 Ajustar Opacidade", callback_data=f"wm_opacity:{user_id}"),
            InlineKeyboardButton("❌ Cancelar", callback_data=f"wm_cancel:{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    watermark_text = context.args[0] if context.args else "@SeuBot"
    
    await update.message.reply_text(
        f"🎨 **Modo Marca D'água Ativado!**\n\n"
        f"📝 Texto atual: `{watermark_text}`\n"
        f"📍 Posição: Canto inferior direito\n"
        f"🎨 Opacidade: 70%\n\n"
        f"📸 **Envie uma imagem** e eu aplicarei a marca d'água automaticamente!\n\n"
        f"⚙️ Use os botões abaixo para personalizar:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Função para download de imagens
async def download_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Baixa imagens do link fornecido."""
    chat_id = update.message.chat_id
    
    if not context.args:
        await send_progress_message(
            context, chat_id,
            "Uso correto: /images [URL]\n\nExemplo: /images https://instagram.com/p/abc123",
            'info'
        )
        return
    
    url = context.args[0]
    await send_progress_message(context, chat_id, "Procurando imagens", 'starting')
    
    # Adiciona à fila
    user_name = update.effective_user.first_name or "Usuário"
    await add_to_queue(chat_id, url, 'images', user_name)
    
    await send_progress_message(
        context, chat_id,
        "Imagens adicionadas à fila\n\n💡 Use /queue para acompanhar",
        'info'
    )
    
    # Inicia processamento se não estiver rodando
    if not is_queue_processing():
        asyncio.create_task(process_download_queue(context))

# Função para processar imagens enviadas
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa imagens enviadas pelo usuário."""
    chat_id = update.message.chat_id
    user_id = update.effective_user.id
    
    # Verifica se o modo marca d'água está ativo
    watermark_mode = context.user_data.get('watermark_mode', {}).get(user_id)
    
    if not watermark_mode or not watermark_mode.get('active'):
        await update.message.reply_text(
            "📸 **Imagem recebida!**\n\n"
            "💡 Para aplicar marca d'água, use o comando `/watermark` primeiro.\n\n"
            "🔗 Ou envie um link de vídeo/imagem para outras opções.",
            parse_mode='Markdown'
        )
        return
    
    try:
        await send_progress_message(
            context, chat_id,
            "📥 Baixando imagem...",
            'downloading', 10
        )
        
        # Baixa a imagem
        photo = update.message.photo[-1]  # Pega a maior resolução
        file = await context.bot.get_file(photo.file_id)
        
        # Cria nome único para o arquivo
        timestamp = int(datetime.now().timestamp())
        image_path = f"{chat_id}_{timestamp}_input.jpg"
        
        await file.download_to_drive(image_path)
        
        await send_progress_message(
            context, chat_id,
            "🎨 Aplicando marca d'água...",
            'processing', 50
        )
        
        # Aplica a marca d'água
        watermark_text = watermark_mode.get('text') or "@SeuBot"
        position = watermark_mode.get('position', 'bottom_right')
        opacity = watermark_mode.get('opacity', 0.7)
        
        await apply_text_watermark(
            context, chat_id, image_path,
            text=watermark_text,
            position=position,
            opacity=opacity
        )
        
        # Desativa o modo marca d'água após uso
        context.user_data['watermark_mode'][user_id]['active'] = False
        
    except Exception as e:
        logger.error(f"Erro ao processar imagem: {e}")
        await send_progress_message(
            context, chat_id,
            f"❌ Erro ao processar imagem: {str(e)[:100]}...",
            'error'
        )

# Função para processar links
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mostra opções para o link enviado pelo usuário."""
    chat_id = update.message.chat_id
    message_text = update.message.text
    
    # Armazena a URL no contexto do usuário
    if 'user_urls' not in context.user_data:
        context.user_data['user_urls'] = {}
    
    url_id = f"{chat_id}_{update.message.message_id}"
    context.user_data['user_urls'][url_id] = message_text
    
    # Detecta plataforma específica
    platform_detected = None
    platform_emoji = "🔗"
    keyboard = []
    
    # TikTok
    if is_tiktok_url(message_text):
        platform_detected = "TikTok"
        platform_emoji = "🎵"
        keyboard = [
            [
                InlineKeyboardButton("🎬 Baixar Vídeo", callback_data=f"tiktok_video:{url_id}"),
                InlineKeyboardButton("🎵 Extrair Áudio", callback_data=f"tiktok_audio:{url_id}")
            ]
        ]
    
    # Twitter/X
    elif is_twitter_url(message_text):
        platform_detected = "Twitter/X"
        platform_emoji = "🐦"
        keyboard = [
            [
                InlineKeyboardButton("🎬 Baixar Vídeo", callback_data=f"twitter_video:{url_id}"),
                InlineKeyboardButton("🎭 Baixar GIF", callback_data=f"twitter_gif:{url_id}")
            ]
        ]
    
    # YouTube Shorts
    elif is_youtube_shorts_url(message_text):
        platform_detected = "YouTube Shorts"
        platform_emoji = "📱"
        keyboard = [
            [
                InlineKeyboardButton("📱 Baixar Short", callback_data=f"youtube_short:{url_id}")
            ]
        ]
    
    # Twitch
    elif is_twitch_url(message_text):
        platform_detected = "Twitch"
        platform_emoji = "🎮"
        if is_twitch_clip_url(message_text):
            keyboard = [
                [
                    InlineKeyboardButton("🎮 Baixar Clipe", callback_data=f"twitch_clip:{url_id}")
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("🎮 Baixar Clipe", callback_data=f"twitch_clip:{url_id}"),
                    InlineKeyboardButton("📺 Baixar VOD", callback_data=f"twitch_vod:{url_id}")
                ]
            ]
    
    # Pinterest
    elif is_pinterest_url(message_text):
        platform_detected = "Pinterest"
        platform_emoji = "📌"
        keyboard = [
            [
                InlineKeyboardButton("📌 Baixar Pin", callback_data=f"pinterest_pin:{url_id}")
            ]
        ]
    
    # LinkedIn
    elif is_linkedin_url(message_text):
        platform_detected = "LinkedIn"
        platform_emoji = "💼"
        content_type = get_linkedin_content_type(message_text)
        if content_type == 'learning':
            keyboard = [
                [
                    InlineKeyboardButton("🎓 Baixar Learning", callback_data=f"linkedin_learning:{url_id}")
                ]
            ]
        else:
            keyboard = [
                [
                    InlineKeyboardButton("💼 Baixar Vídeo", callback_data=f"linkedin_video:{url_id}")
                ]
            ]
    
    # Telegram
    elif is_telegram_url(message_text):
        platform_detected = "Telegram"
        platform_emoji = "📱"
        if is_telegram_channel_url(message_text):
            keyboard = [
                [
                    InlineKeyboardButton("📱 Baixar Canal (5)", callback_data=f"telegram_channel:{url_id}")
                ]
            ]
        elif is_telegram_message_url(message_text):
            keyboard = [
                [
                    InlineKeyboardButton("📱 Baixar Mensagem", callback_data=f"telegram_message:{url_id}")
                ]
            ]
    
    # Instagram Stories
    elif is_story_url(message_text):
        platform_detected = "Instagram Story"
        platform_emoji = "📱"
        keyboard = [
            [
                InlineKeyboardButton("📱 Baixar Story", callback_data=f"story:{url_id}")
            ],
            [
                InlineKeyboardButton("🎬 Tentar como Vídeo", callback_data=f"video:{url_id}"),
                InlineKeyboardButton("🖼️ Tentar como Imagens", callback_data=f"images:{url_id}")
            ]
        ]
    
    # Instagram padrão
    elif 'instagram.com' in message_text.lower():
        platform_detected = "Instagram"
        platform_emoji = "📸"
        keyboard = [
            [
                InlineKeyboardButton("🎬 Baixar Vídeo", callback_data=f"video:{url_id}"),
                InlineKeyboardButton("🖼️ Baixar Imagens", callback_data=f"images:{url_id}")
            ],
            [
                InlineKeyboardButton("📱 É um Story?", callback_data=f"story:{url_id}")
            ]
        ]
    
    # YouTube vertical (possível Short)
    elif is_vertical_youtube_video(message_text):
        platform_detected = "YouTube"
        platform_emoji = "📺"
        keyboard = [
            [
                InlineKeyboardButton("📱 Como Short", callback_data=f"youtube_short:{url_id}"),
                InlineKeyboardButton("🎬 Como Vídeo", callback_data=f"video:{url_id}")
            ]
        ]
    
    # Padrão para outros links
    else:
        platform_detected = "Link genérico"
        keyboard = [
            [
                InlineKeyboardButton("🎬 Baixar Vídeo", callback_data=f"video:{url_id}"),
                InlineKeyboardButton("🖼️ Baixar Imagens", callback_data=f"images:{url_id}")
            ]
        ]
    
    # Adiciona opções extras se não for plataforma específica
    if not platform_detected or platform_detected in ["Link genérico", "Instagram", "YouTube"]:
        keyboard.append([
            InlineKeyboardButton("⚙️ Opções Avançadas", callback_data=f"advanced:{url_id}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Monta mensagem
    if platform_detected and platform_detected != "Link genérico":
        message_type = f"{platform_emoji} **{platform_detected} detectado!**"
        if platform_detected == "Instagram Story":
            extra_info = "\n\n⚠️ **Lembre-se:** Stories expiram em 24h!"
        else:
            extra_info = ""
    else:
        message_type = f"{platform_emoji} **Link detectado!**"
        extra_info = ""
    
    await update.message.reply_text(
        f"{message_type}\n\n"
        f"📎 `{message_text[:50]}...`{extra_info}\n\n"
        f"Escolha uma opção:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Processador da fila de downloads (versão simplificada)
async def process_download_queue(context):
    """Processa a fila de downloads sequencialmente."""
    global current_download
    
    while True:
        try:
            item = await get_next_queue_item()
            
            if not item:
                current_download = None
                logger.info("Fila de downloads vazia, parando processamento")
                # Limpeza automática
                try:
                    cleanup_temp_files()
                except Exception as e:
                    logger.warning(f"Erro na limpeza automática: {e}")
                break
            
            current_download = item
            item.status = 'downloading'
            item.started_time = datetime.now().isoformat()
            save_queue()
            
            # Notifica usuário
            type_emojis = {'video': '🎬', 'images': '🖼️', 'audio': '🎵'}
            type_emoji = type_emojis.get(item.download_type, '📁')
            
            await send_progress_message(
                context,
                item.chat_id,
                f"Download iniciado\n\n{type_emoji} {item.download_type.title()}\n📎 {item.url[:50]}...",
                'downloading',
                0
            )
            
            # Simula processamento (implementar lógica real)
            await asyncio.sleep(2)
            
            # Marca como concluído
            item.status = 'completed'
            item.completed_time = datetime.now().isoformat()
            
            await send_progress_message(
                context,
                item.chat_id,
                f"Download concluído\n\n{type_emoji} {item.download_type.title()} processado!",
                'completed',
                100
            )
            
            save_queue()
            await asyncio.sleep(1)
            
        except Exception as e:
            if current_download:
                current_download.status = 'failed'
                current_download.error_message = str(e)[:100]
                save_queue()
            
            logger.error(f"Erro no processamento da fila: {e}")
            break
    
    current_download = None

# Função de callback para botões
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processa os callbacks dos botões inline."""
    query = update.callback_query
    await query.answer()
    
    callback_parts = query.data.split(':', 2)
    action = callback_parts[0]
    chat_id = query.message.chat_id
    
    # Função auxiliar para recuperar URL
    def get_url_from_context(url_id):
        if 'user_urls' in context.user_data and url_id in context.user_data['user_urls']:
            return context.user_data['user_urls'][url_id]
        return url_id
    
    # Handlers para o menu principal
    if action == 'menu_queue':
        await query.edit_message_text("📋 **Abrindo sua fila de downloads...**")
        fake_update = type('obj', (object,), {
            'message': type('obj', (object,), {
                'chat_id': chat_id,
                'reply_text': query.message.reply_text
            })()
        })()
        await show_queue(fake_update, context)
        
    elif action == 'menu_cleanup':
        await query.edit_message_text("🧹 **Limpando arquivos temporários...**")
        fake_update = type('obj', (object,), {
            'message': type('obj', (object,), {
                'chat_id': chat_id,
                'reply_text': query.message.reply_text
            })()
        })()
        await cleanup_files(fake_update, context)
        
    elif action == 'menu_help':
        fake_update = type('obj', (object,), {
            'message': type('obj', (object,), {
                'chat_id': chat_id,
                'reply_text': query.message.reply_text
            })()
        })()
        await help_command(fake_update, context)
    
    # Handlers para novos downloaders
    elif action.startswith('tiktok_'):
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"🎵 **Processando TikTok...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        if action == 'tiktok_video':
            await download_tiktok_video(query, context, url)
        elif action == 'tiktok_audio':
            await download_tiktok_audio(query, context, url)
    
    elif action.startswith('twitter_'):
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"🐦 **Processando Twitter/X...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        if action == 'twitter_video':
            await download_twitter_video(query, context, url)
        elif action == 'twitter_gif':
            await download_twitter_gif(query, context, url)
    
    elif action == 'youtube_short':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"📱 **Processando YouTube Short...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        await download_youtube_short(query, context, url)
    
    elif action.startswith('twitch_'):
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"🎮 **Processando Twitch...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        if action == 'twitch_clip':
            await download_twitch_clip(query, context, url)
        # twitch_vod seria implementado posteriormente
    
    elif action == 'pinterest_pin':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"📌 **Processando Pinterest...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        await download_pinterest_pin(query, context, url)
    
    elif action.startswith('linkedin_'):
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"💼 **Processando LinkedIn...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        await download_linkedin_video(query, context, url)
    
    elif action.startswith('telegram_'):
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        await query.edit_message_text(f"📱 **Processando Telegram...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        if action == 'telegram_channel':
            await download_telegram_channel(query, context, url, 5)
        elif action == 'telegram_message':
            await download_telegram_message(query, context, url)
    
    # Handlers originais
    elif action in ['video', 'images', 'story']:
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        user_name = query.from_user.first_name or "Usuário"
        
        download_type = 'video' if action == 'video' else action
        
        await query.edit_message_text(f"⬇️ **Adicionando à fila...**\n\n📎 `{url[:50]}...`", parse_mode='Markdown')
        
        await add_to_queue(chat_id, url, download_type, user_name)
        
        await send_progress_message(
            context, chat_id,
            f"{action.title()} adicionado à fila\n\n💡 Use /queue para acompanhar",
            'info'
        )
        
        if not is_queue_processing():
            asyncio.create_task(process_download_queue(context))
    
    # Handler para opções avançadas
    elif action == 'advanced':
        url_id = callback_parts[1]
        url = get_url_from_context(url_id)
        
        # Cria menu de opções avançadas
        advanced_keyboard = [
            [
                InlineKeyboardButton("✂️ Cortar Vídeo", callback_data=f"cut_video:{url_id}"),
                InlineKeyboardButton("🎵 Extrair Áudio", callback_data=f"extract_audio:{url_id}")
            ],
            [
                InlineKeyboardButton("📊 Ver Informações", callback_data=f"info:{url_id}"),
                InlineKeyboardButton("🔙 Voltar", callback_data=f"back:{url_id}")
            ]
        ]
        
        await query.edit_message_text(
            f"⚙️ **Opções Avançadas**\n\n📎 `{url[:50]}...`\n\nEscolha uma opção:",
            reply_markup=InlineKeyboardMarkup(advanced_keyboard),
            parse_mode='Markdown'
        )
    
    # Handlers para fila
    elif action == 'queue_refresh':
        fake_update = type('obj', (object,), {
            'message': type('obj', (object,), {
                'chat_id': chat_id,
                'reply_text': query.message.reply_text
            })()
        })()
        await show_queue(fake_update, context)
    
    elif action == 'queue_clear_completed':
        await clear_completed_items(chat_id)
        await query.edit_message_text("🗑️ **Itens concluídos removidos!**", parse_mode='Markdown')
    
    elif action == 'queue_clear_all':
        await clear_user_queue(chat_id)
        await query.edit_message_text("❌ **Fila limpa!**", parse_mode='Markdown')
    
    # Handlers para marca d'água
    elif action.startswith('wm_'):
        user_id = int(callback_parts[1])
        
        if action == 'wm_cancel':
            if 'watermark_mode' in context.user_data and user_id in context.user_data['watermark_mode']:
                context.user_data['watermark_mode'][user_id]['active'] = False
            await query.edit_message_text("❌ **Modo marca d'água cancelado!**", parse_mode='Markdown')
        
        elif action == 'wm_position':
            keyboard = [
                [
                    InlineKeyboardButton("↖️ Superior Esquerda", callback_data=f"wm_pos_top_left:{user_id}"),
                    InlineKeyboardButton("↗️ Superior Direita", callback_data=f"wm_pos_top_right:{user_id}")
                ],
                [
                    InlineKeyboardButton("↙️ Inferior Esquerda", callback_data=f"wm_pos_bottom_left:{user_id}"),
                    InlineKeyboardButton("↘️ Inferior Direita", callback_data=f"wm_pos_bottom_right:{user_id}")
                ],
                [
                    InlineKeyboardButton("🎯 Centro", callback_data=f"wm_pos_center:{user_id}"),
                    InlineKeyboardButton("🔙 Voltar", callback_data=f"wm_back:{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "📍 **Escolha a posição da marca d'água:**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        elif action == 'wm_opacity':
            keyboard = [
                [
                    InlineKeyboardButton("🌟 100%", callback_data=f"wm_op_1.0:{user_id}"),
                    InlineKeyboardButton("✨ 80%", callback_data=f"wm_op_0.8:{user_id}")
                ],
                [
                    InlineKeyboardButton("💫 60%", callback_data=f"wm_op_0.6:{user_id}"),
                    InlineKeyboardButton("🌙 40%", callback_data=f"wm_op_0.4:{user_id}")
                ],
                [
                    InlineKeyboardButton("👻 20%", callback_data=f"wm_op_0.2:{user_id}"),
                    InlineKeyboardButton("🔙 Voltar", callback_data=f"wm_back:{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🎨 **Escolha a opacidade da marca d'água:**",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    elif action.startswith('wm_pos_'):
        user_id = int(callback_parts[1])
        position = action.replace('wm_pos_', '')
        
        if 'watermark_mode' in context.user_data and user_id in context.user_data['watermark_mode']:
            context.user_data['watermark_mode'][user_id]['position'] = position
        
        position_names = {
            'top_left': 'Superior Esquerda',
            'top_right': 'Superior Direita',
            'bottom_left': 'Inferior Esquerda',
            'bottom_right': 'Inferior Direita',
            'center': 'Centro'
        }
        
        await query.edit_message_text(
            f"✅ **Posição alterada para:** {position_names.get(position, position)}\n\n"
            f"📸 Agora envie uma imagem para aplicar a marca d'água!",
            parse_mode='Markdown'
        )
    
    elif action.startswith('wm_op_'):
        user_id = int(callback_parts[1])
        opacity = float(action.replace('wm_op_', ''))
        
        if 'watermark_mode' in context.user_data and user_id in context.user_data['watermark_mode']:
            context.user_data['watermark_mode'][user_id]['opacity'] = opacity
        
        await query.edit_message_text(
            f"✅ **Opacidade alterada para:** {int(opacity * 100)}%\n\n"
            f"📸 Agora envie uma imagem para aplicar a marca d'água!",
            parse_mode='Markdown'
        )
    
    elif action == 'wm_back':
        user_id = int(callback_parts[1])
        watermark_mode = context.user_data.get('watermark_mode', {}).get(user_id, {})
        
        keyboard = [
            [
                InlineKeyboardButton("📝 Personalizar Texto", callback_data=f"wm_text:{user_id}"),
                InlineKeyboardButton("📍 Mudar Posição", callback_data=f"wm_position:{user_id}")
            ],
            [
                InlineKeyboardButton("🎨 Ajustar Opacidade", callback_data=f"wm_opacity:{user_id}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"wm_cancel:{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        watermark_text = watermark_mode.get('text') or "@SeuBot"
        position_names = {
            'top_left': 'Superior Esquerda',
            'top_right': 'Superior Direita', 
            'bottom_left': 'Inferior Esquerda',
            'bottom_right': 'Inferior Direita',
            'center': 'Centro'
        }
        position_name = position_names.get(watermark_mode.get('position', 'bottom_right'), 'Inferior Direita')
        opacity_percent = int(watermark_mode.get('opacity', 0.7) * 100)
        
        await query.edit_message_text(
            f"🎨 **Modo Marca D'água Ativado!**\n\n"
            f"📝 Texto atual: `{watermark_text}`\n"
            f"📍 Posição: {position_name}\n"
            f"🎨 Opacidade: {opacity_percent}%\n\n"
            f"📸 **Envie uma imagem** e eu aplicarei a marca d'água automaticamente!\n\n"
            f"⚙️ Use os botões abaixo para personalizar:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

def main() -> None:
    """Inicia o bot."""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("Token do Telegram não encontrado! Defina a variável de ambiente TELEGRAM_TOKEN.")
    
    application = Application.builder().token(token).build()
    
    # Limpeza inicial
    try:
        removed_files = cleanup_temp_files()
        logger.info(f"Limpeza inicial: {removed_files} arquivos removidos")
    except Exception as e:
        logger.warning(f"Erro na limpeza inicial: {e}")
    
    # Adiciona os handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("images", download_images))
    application.add_handler(CommandHandler("story", download_story))
    application.add_handler(CommandHandler("queue", show_queue))
    application.add_handler(CommandHandler("clear_queue", clear_queue))
    application.add_handler(CommandHandler("cleanup", cleanup_files))
    application.add_handler(CommandHandler("cut", cut_video))
    application.add_handler(CommandHandler("watermark", watermark_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    
    logger.info("Bot iniciado e aguardando mensagens...")
    application.run_polling()

if __name__ == '__main__':
    main()
