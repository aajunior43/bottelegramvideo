#!/usr/bin/env python3
"""
Bot Telegram para Download de Vídeos - Versão Refatorada
Versão: 2.1.0
Autor: Bot Telegram Video Downloader

Melhorias implementadas:
- Separação de responsabilidades em classes
- Melhor organização do código
- Handlers organizados por funcionalidade
- Configuração centralizada
- Melhor tratamento de erros
- Logging estruturado
"""

import logging
import os
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, CallbackQueryHandler
)

# Importações locais
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

# Importações de downloaders específicos
from tiktok_downloader import download_tiktok_video, download_tiktok_audio, is_tiktok_url
from twitter_downloader import download_twitter_video, download_twitter_gif, is_twitter_url
from twitch_downloader import download_twitch_clip, is_twitch_url, is_twitch_clip_url
from pinterest_downloader import download_pinterest_pin, is_pinterest_url
from linkedin_downloader import download_linkedin_video, is_linkedin_url, get_linkedin_content_type
from telegram_downloader import (
    download_telegram_channel, download_telegram_message, is_telegram_url,
    is_telegram_channel_url, is_telegram_message_url
)
from watermark_processor import apply_text_watermark, apply_logo_watermark, watermark_processor


@dataclass
class BotConfig:
    """Configuração centralizada do bot."""
    token: str
    log_level: str = "INFO"
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    temp_cleanup_interval: int = 3600  # 1 hora
    
    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Cria configuração a partir de variáveis de ambiente."""
        load_dotenv()
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            raise ValueError("Token do Telegram não encontrado! Defina TELEGRAM_TOKEN.")
        
        return cls(
            token=token,
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            max_file_size=int(os.getenv("MAX_FILE_SIZE", 50 * 1024 * 1024)),
            temp_cleanup_interval=int(os.getenv("TEMP_CLEANUP_INTERVAL", 3600))
        )


class PlatformDetector:
    """Detecta plataformas e retorna configurações específicas."""
    
    @staticmethod
    def detect_platform(url: str) -> Dict[str, Any]:
        """Detecta a plataforma da URL e retorna configurações."""
        url_lower = url.lower()
        
        # TikTok
        if is_tiktok_url(url):
            return {
                'platform': 'TikTok',
                'emoji': '🎵',
                'buttons': [
                    [InlineKeyboardButton("🎬 Baixar Vídeo", callback_data="tiktok_video"),
                     InlineKeyboardButton("🎵 Extrair Áudio", callback_data="tiktok_audio")]
                ]
            }
        
        # Twitter/X
        elif is_twitter_url(url):
            return {
                'platform': 'Twitter/X',
                'emoji': '🐦',
                'buttons': [
                    [InlineKeyboardButton("🎬 Baixar Vídeo", callback_data="twitter_video"),
                     InlineKeyboardButton("🎭 Baixar GIF", callback_data="twitter_gif")]
                ]
            }
        
        # Twitch
        elif is_twitch_url(url):
            buttons = [[InlineKeyboardButton("🎮 Baixar Clipe", callback_data="twitch_clip")]]
            if not is_twitch_clip_url(url):
                buttons[0].append(InlineKeyboardButton("📺 Baixar VOD", callback_data="twitch_vod"))
            
            return {
                'platform': 'Twitch',
                'emoji': '🎮',
                'buttons': buttons
            }
        
        # Pinterest
        elif is_pinterest_url(url):
            return {
                'platform': 'Pinterest',
                'emoji': '📌',
                'buttons': [
                    [InlineKeyboardButton("📌 Baixar Pin", callback_data="pinterest_pin")]
                ]
            }
        
        # LinkedIn
        elif is_linkedin_url(url):
            content_type = get_linkedin_content_type(url)
            button_text = "🎓 Baixar Learning" if content_type == 'learning' else "💼 Baixar Vídeo"
            callback_data = f"linkedin_{content_type}" if content_type == 'learning' else "linkedin_video"
            
            return {
                'platform': 'LinkedIn',
                'emoji': '💼',
                'buttons': [
                    [InlineKeyboardButton(button_text, callback_data=callback_data)]
                ]
            }
        
        # Telegram
        elif is_telegram_url(url):
            if is_telegram_channel_url(url):
                buttons = [[InlineKeyboardButton("📱 Baixar Canal (5)", callback_data="telegram_channel")]]
            elif is_telegram_message_url(url):
                buttons = [[InlineKeyboardButton("📱 Baixar Mensagem", callback_data="telegram_message")]]
            else:
                buttons = [[InlineKeyboardButton("📱 Baixar", callback_data="telegram_generic")]]
            
            return {
                'platform': 'Telegram',
                'emoji': '📱',
                'buttons': buttons
            }
        
        # Instagram Stories
        elif is_story_url(url):
            return {
                'platform': 'Instagram Story',
                'emoji': '📱',
                'buttons': [
                    [InlineKeyboardButton("📱 Baixar Story", callback_data="story")],
                    [InlineKeyboardButton("🎬 Tentar como Vídeo", callback_data="video"),
                     InlineKeyboardButton("🖼️ Tentar como Imagens", callback_data="images")]
                ],
                'extra_info': "\n\n⚠️ **Lembre-se:** Stories expiram em 24h!"
            }
        
        # Instagram padrão
        elif 'instagram.com' in url_lower:
            return {
                'platform': 'Instagram',
                'emoji': '📸',
                'buttons': [
                    [InlineKeyboardButton("🎬 Baixar Vídeo", callback_data="video"),
                     InlineKeyboardButton("🖼️ Baixar Imagens", callback_data="images")],
                    [InlineKeyboardButton("📱 É um Story?", callback_data="story")]
                ]
            }
        
        # Padrão para outros links
        else:
            return {
                'platform': 'Link genérico',
                'emoji': '🔗',
                'buttons': [
                    [InlineKeyboardButton("📋 Ver Qualidades", callback_data="qualities"),
                     InlineKeyboardButton("🎬 Baixar Melhor", callback_data="video")],
                    [InlineKeyboardButton("🖼️ Baixar Imagens", callback_data="images")]
                ]
            }


class CommandHandlers:
    """Handlers para comandos do bot."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /start com menu principal."""
        user = update.effective_user
        
        keyboard = [
            [InlineKeyboardButton("📋 Ver Fila", callback_data="menu_queue"),
             InlineKeyboardButton("🧹 Limpar Arquivos", callback_data="menu_cleanup")],
            [InlineKeyboardButton("✂️ Cortar Vídeo", callback_data="menu_cut"),
             InlineKeyboardButton("📱 Download Story", callback_data="menu_story")],
            [InlineKeyboardButton("🖼️ Download Imagens", callback_data="menu_images"),
             InlineKeyboardButton("❓ Ajuda", callback_data="menu_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"🤖 **Olá, {user.mention_html()}!**\n\n"
            "📱 **Como usar:**\n"
            "• Envie um link diretamente no chat\n"
            "• Ou use os botões abaixo para funções específicas\n\n"
            "🎬 **Plataformas suportadas:**\n"
            "YouTube, TikTok, Instagram, Facebook e muito mais!\n\n"
            "👇 **Escolha uma opção:**",
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Comando /help com informações detalhadas."""
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
            "• `/cleanup` - Limpar arquivos temporários"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')


class MessageHandlers:
    """Handlers para mensagens do bot."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.platform_detector = PlatformDetector()
    
    async def handle_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Processa links enviados pelo usuário."""
        chat_id = update.message.chat_id
        message_text = update.message.text
        
        # Armazena URL no contexto
        if 'user_urls' not in context.user_data:
            context.user_data['user_urls'] = {}
        
        url_id = f"{chat_id}_{update.message.message_id}"
        context.user_data['user_urls'][url_id] = message_text
        
        # Detecta plataforma
        platform_info = self.platform_detector.detect_platform(message_text)
        
        # Adiciona url_id aos callbacks
        for row in platform_info['buttons']:
            for button in row:
                button.callback_data += f":{url_id}"
        
        # Adiciona opções avançadas se necessário
        if platform_info['platform'] in ["Link genérico", "Instagram", "YouTube"]:
            platform_info['buttons'].append([
                InlineKeyboardButton("⚙️ Opções Avançadas", callback_data=f"advanced:{url_id}")
            ])
        
        reply_markup = InlineKeyboardMarkup(platform_info['buttons'])
        
        # Monta mensagem
        extra_info = platform_info.get('extra_info', '')
        message_type = f"{platform_info['emoji']} **{platform_info['platform']} detectado!**"
        
        await update.message.reply_text(
            f"{message_type}\n\n"
            f"📎 `{message_text[:50]}...`{extra_info}\n\n"
            f"Escolha uma opção:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Processa imagens enviadas pelo usuário."""
        chat_id = update.message.chat_id
        user_id = update.effective_user.id
        
        # Verifica modo marca d'água
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
                context, chat_id, "📥 Baixando imagem...", 'downloading', 10
            )
            
            # Baixa a imagem
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            timestamp = int(datetime.now().timestamp())
            image_path = f"{chat_id}_{timestamp}_input.jpg"
            
            await file.download_to_drive(image_path)
            
            # Aplica marca d'água
            watermark_text = watermark_mode.get('text') or "@SeuBot"
            position = watermark_mode.get('position', 'bottom_right')
            opacity = watermark_mode.get('opacity', 0.7)
            
            await apply_text_watermark(
                context, chat_id, image_path,
                text=watermark_text, position=position, opacity=opacity
            )
            
            # Desativa modo após uso
            context.user_data['watermark_mode'][user_id]['active'] = False
            
        except Exception as e:
            self.logger.error(f"Erro ao processar imagem: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro ao processar imagem: {str(e)[:100]}...",
                'error'
            )


class TelegramBot:
    """Classe principal do bot Telegram."""
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.logger = self._setup_logging()
        self.application = Application.builder().token(config.token).build()
        
        # Inicializa handlers
        self.command_handlers = CommandHandlers(config)
        self.message_handlers = MessageHandlers(config)
        
        self._setup_handlers()
    
    def _setup_logging(self) -> logging.Logger:
        """Configura o sistema de logging."""
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=getattr(logging, self.config.log_level)
        )
        return logging.getLogger(self.__class__.__name__)
    
    def _setup_handlers(self) -> None:
        """Configura todos os handlers do bot."""
        # Comandos básicos
        self.application.add_handler(CommandHandler("start", self.command_handlers.start))
        self.application.add_handler(CommandHandler("help", self.command_handlers.help_command))
        
        # Handlers de mensagem
        self.application.add_handler(MessageHandler(filters.PHOTO, self.message_handlers.handle_photo))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message_handlers.handle_link))
        
        # TODO: Adicionar outros handlers (callback, comandos específicos, etc.)
    
    def run(self) -> None:
        """Inicia o bot."""
        try:
            # Limpeza inicial
            removed_files = cleanup_temp_files()
            self.logger.info(f"Limpeza inicial: {removed_files} arquivos removidos")
        except Exception as e:
            self.logger.warning(f"Erro na limpeza inicial: {e}")
        
        self.logger.info("Bot iniciado e aguardando mensagens...")
        self.application.run_polling()


def main() -> None:
    """Função principal."""
    try:
        config = BotConfig.from_env()
        bot = TelegramBot(config)
        bot.run()
    except Exception as e:
        logging.error(f"Erro fatal: {e}")
        raise


if __name__ == '__main__':
    main()