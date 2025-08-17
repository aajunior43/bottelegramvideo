import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, is_good_quality_image
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class TelegramDownloader:
    """Downloader específico para Telegram com suporte a mídia de canais públicos."""
    
    def __init__(self):
        self.platform = "Telegram"
        self.supported_domains = [
            't.me',
            'telegram.me',
            'telegram.org'
        ]
    
    def is_telegram_url(self, url):
        """Verifica se a URL é do Telegram."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    def is_telegram_channel(self, url):
        """Verifica se a URL é de um canal do Telegram."""
        url_lower = url.lower()
        return 't.me/' in url_lower and '/s/' not in url_lower
    
    def is_telegram_message(self, url):
        """Verifica se a URL é de uma mensagem específica do Telegram."""
        url_lower = url.lower()
        return 't.me/' in url_lower and ('/' in url_lower.split('t.me/')[-1])
    
    async def download_channel_media(self, update, context, channel_url, limit=5):
        """Baixa mídia de um canal público do Telegram."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📱 Baixando mídia do canal Telegram\n\n📎 {channel_url[:50]}...\n\n⚠️ Limite: {limit} arquivos",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_telegram_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando yt-dlp para canal Telegram
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--write-thumbnail',
                '--write-info-json',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--yes-playlist',
                '--extract-flat', 'false',
                channel_url
            ]
            
            logger.info(f"Executando comando canal Telegram: {' '.join(command)}")
            
            # Executa o comando
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                await send_progress_message(
                    context, chat_id,
                    "📱 Download concluído! Processando mídia...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_telegram_"):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    # Separa vídeos e imagens
                    videos = [f for f in downloaded_files if f.endswith(('.mp4', '.webm', '.mkv'))]
                    images = [f for f in downloaded_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                    audios = [f for f in downloaded_files if f.endswith(('.mp3', '.ogg', '.m4a'))]
                    
                    sent_count = 0
                    
                    await send_progress_message(
                        context, chat_id,
                        f"📱 Enviando {len(downloaded_files)} arquivos...\n\n🎬 Vídeos: {len(videos)}\n🖼️ Imagens: {len(images)}\n🎵 Áudios: {len(audios)}",
                        'processing', 50
                    )
                    
                    # Envia vídeos
                    for i, video_file in enumerate(videos, 1):
                        try:
                            await send_video_with_fallback(
                                chat_id, video_file, context,
                                f"📱 Canal Telegram - Vídeo {i}/{len(videos)}\n\n📎 {channel_url[:50]}..."
                            )
                            os.remove(video_file)
                            sent_count += 1
                            logger.info(f"Vídeo Telegram enviado e removido: {video_file}")
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo Telegram {video_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(videos):
                            await asyncio.sleep(1)
                    
                    # Envia imagens (apenas as de boa qualidade)
                    good_images = [img for img in images if is_good_quality_image(img)]
                    
                    for i, image_file in enumerate(good_images, 1):
                        try:
                            with open(image_file, 'rb') as img:
                                await context.bot.send_photo(
                                    chat_id,
                                    photo=img,
                                    caption=f"📱 Canal Telegram - Imagem {i}/{len(good_images)}\n\n📎 {channel_url[:50]}..."
                                )
                            sent_count += 1
                            logger.info(f"Imagem Telegram enviada: {image_file}")
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem Telegram {image_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(good_images):
                            await asyncio.sleep(1)
                    
                    # Envia áudios
                    for i, audio_file in enumerate(audios, 1):
                        try:
                            with open(audio_file, 'rb') as audio:
                                await context.bot.send_audio(
                                    chat_id,
                                    audio=audio,
                                    caption=f"📱 Canal Telegram - Áudio {i}/{len(audios)}\n\n📎 {channel_url[:50]}..."
                                )
                            sent_count += 1
                            logger.info(f"Áudio Telegram enviado: {audio_file}")
                        except Exception as e:
                            logger.error(f"Erro ao enviar áudio Telegram {audio_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(audios):
                            await asyncio.sleep(1)
                    
                    # Remove todos os arquivos temporários
                    for file in downloaded_files:
                        try:
                            if os.path.exists(file):
                                os.remove(file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ Canal Telegram processado!\n\n📊 {sent_count} arquivos enviados",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhuma mídia encontrada\n\n💡 O canal pode não ter mídia pública ou estar vazio",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para canal Telegram: {error_message}")
                
                # Verifica erros específicos do Telegram
                if 'private' in error_message.lower():
                    error_msg = "❌ Canal privado\n\n💡 Apenas canais públicos podem ser acessados"
                elif 'not found' in error_message.lower():
                    error_msg = "❌ Canal não encontrado\n\n💡 Verifique se o nome do canal está correto"
                elif 'restricted' in error_message.lower():
                    error_msg = "❌ Canal restrito\n\n💡 O canal pode ter restrições geográficas"
                else:
                    error_msg = f"❌ Erro ao acessar canal Telegram\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download canal Telegram: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_message_media(self, update, context, message_url):
        """Baixa mídia de uma mensagem específica do Telegram."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📱 Baixando mensagem Telegram\n\n📎 {message_url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída para mensagem específica
            output_template = f"{chat_id}_{message_id}_telegram_msg_%(title)s.%(ext)s"
            
            # Comando para mensagem específica
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--write-thumbnail',
                '--write-info-json',
                '--output', output_template,
                '--no-playlist',
                message_url
            ]
            
            logger.info(f"Executando comando mensagem Telegram: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                message_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_telegram_msg_"):
                        message_files.append(file)
                
                if message_files:
                    # Processa cada arquivo
                    for msg_file in message_files:
                        if msg_file.endswith(('.mp4', '.webm', '.mkv')):
                            # É vídeo
                            await send_video_with_fallback(
                                chat_id, msg_file, context,
                                f"📱 Telegram Message\n\n📎 {message_url[:50]}..."
                            )
                        elif msg_file.endswith(('.jpg', '.jpeg', '.png', '.webp')):
                            # É imagem
                            if is_good_quality_image(msg_file):
                                with open(msg_file, 'rb') as img:
                                    await context.bot.send_photo(
                                        chat_id,
                                        photo=img,
                                        caption=f"📱 Telegram Message\n\n📎 {message_url[:50]}..."
                                    )
                        elif msg_file.endswith(('.mp3', '.ogg', '.m4a')):
                            # É áudio
                            with open(msg_file, 'rb') as audio:
                                await context.bot.send_audio(
                                    chat_id,
                                    audio=audio,
                                    caption=f"📱 Telegram Message\n\n📎 {message_url[:50]}..."
                                )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(msg_file)
                            logger.info(f"Arquivo mensagem removido: {msg_file}")
                        except Exception as e:
                            logger.warning(f"Erro ao remover {msg_file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Mensagem Telegram baixada com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhuma mídia encontrada na mensagem",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar mensagem\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de mensagem Telegram: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de mensagem\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_channel_info(self, channel_url):
        """Obtém informações do canal Telegram."""
        try:
            command = [
                'yt-dlp',
                '--dump-json',
                '--playlist-items', '1',  # Apenas o primeiro item para info
                channel_url
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                import json
                lines = stdout.decode().strip().split('\n')
                if lines:
                    info = json.loads(lines[0])
                    return {
                        'title': info.get('playlist_title', 'Canal Telegram'),
                        'channel': info.get('uploader', 'Desconhecido'),
                        'description': info.get('description', ''),
                        'entry_count': info.get('playlist_count', 0),
                        'url': channel_url
                    }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do canal Telegram: {e}")
            return None
    
    def extract_channel_name(self, url):
        """Extrai o nome do canal da URL."""
        try:
            if 't.me/' in url:
                return url.split('t.me/')[-1].split('/')[0]
            return 'unknown'
        except:
            return 'unknown'
    
    def is_public_channel(self, url):
        """Verifica se é um canal público (heurística básica)."""
        # Canais públicos geralmente têm nomes sem caracteres especiais
        channel_name = self.extract_channel_name(url)
        return channel_name and not channel_name.startswith('+') and len(channel_name) > 3

# Instância global do downloader
telegram_downloader = TelegramDownloader()

# Funções de conveniência para uso externo
async def download_telegram_channel(update, context, channel_url, limit=5):
    """Função de conveniência para download de canal Telegram."""
    return await telegram_downloader.download_channel_media(update, context, channel_url, limit)

async def download_telegram_message(update, context, message_url):
    """Função de conveniência para download de mensagem Telegram."""
    return await telegram_downloader.download_message_media(update, context, message_url)

def is_telegram_url(url):
    """Função de conveniência para verificar URL Telegram."""
    return telegram_downloader.is_telegram_url(url)

def is_telegram_channel_url(url):
    """Função de conveniência para verificar URL de canal Telegram."""
    return telegram_downloader.is_telegram_channel(url)

def is_telegram_message_url(url):
    """Função de conveniência para verificar URL de mensagem Telegram."""
    return telegram_downloader.is_telegram_message(url)

def is_public_telegram_channel(url):
    """Função de conveniência para verificar se é canal público."""
    return telegram_downloader.is_public_channel(url)

async def get_telegram_channel_info(url):
    """Função de conveniência para obter informações do canal Telegram."""
    return await telegram_downloader.get_channel_info(url)

def extract_telegram_channel_name(url):
    """Função de conveniência para extrair nome do canal."""
    return telegram_downloader.extract_channel_name(url)