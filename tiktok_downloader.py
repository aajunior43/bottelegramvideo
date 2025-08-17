import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, check_ffmpeg
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class TikTokDownloader:
    """Downloader específico para TikTok com suporte a vídeos e áudios."""
    
    def __init__(self):
        self.platform = "TikTok"
        self.supported_domains = [
            'tiktok.com',
            'vm.tiktok.com',
            'vt.tiktok.com',
            'm.tiktok.com'
        ]
    
    def is_tiktok_url(self, url):
        """Verifica se a URL é do TikTok."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    async def download_video(self, update, context, url, quality='best'):
        """Baixa vídeo do TikTok."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎵 Iniciando download do TikTok\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_tiktok_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para TikTok
            command = [
                'yt-dlp',
                '--format', f'{quality}[height<=1080]/best[height<=1080]/best',
                '--write-thumbnail',
                '--write-description',
                '--write-info-json',
                '--merge-output-format', 'mp4',
                '--output', output_template,
                '--no-playlist',
                '--extract-flat', 'false',
                url
            ]
            
            logger.info(f"Executando comando TikTok: {' '.join(command)}")
            
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
                    "🎵 Download concluído! Processando arquivo...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_tiktok_") and file.endswith('.mp4'):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    video_file = downloaded_files[0]
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, video_file, context,
                        f"🎵 TikTok Video\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_tiktok_"):
                            try:
                                os.remove(file)
                                logger.info(f"Arquivo removido: {file}")
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ TikTok baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado\n\n💡 Verifique se o vídeo ainda está disponível",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para TikTok: {error_message}")
                
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar do TikTok\n\nPossíveis causas:\n• Vídeo privado ou removido\n• URL inválida\n• Restrições geográficas\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download TikTok: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_audio(self, update, context, url):
        """Baixa apenas o áudio do TikTok."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎵 Extraindo áudio do TikTok\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída para áudio
            output_template = f"{chat_id}_{message_id}_tiktok_audio_%(title)s.%(ext)s"
            
            # Comando para extrair apenas áudio
            command = [
                'yt-dlp',
                '--format', 'bestaudio/best',
                '--extract-audio',
                '--audio-format', 'mp3',
                '--audio-quality', '192K',
                '--output', output_template,
                '--no-playlist',
                url
            ]
            
            logger.info(f"Executando comando áudio TikTok: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos de áudio
                audio_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_tiktok_audio_") and file.endswith('.mp3'):
                        audio_files.append(file)
                
                if audio_files:
                    audio_file = audio_files[0]
                    
                    # Envia o áudio
                    with open(audio_file, 'rb') as audio:
                        await context.bot.send_audio(
                            chat_id,
                            audio=audio,
                            caption=f"🎵 TikTok Audio\n\n📎 {url[:50]}..."
                        )
                    
                    # Remove arquivo temporário
                    os.remove(audio_file)
                    logger.info(f"Áudio TikTok enviado e removido: {audio_file}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Áudio do TikTok extraído com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Não foi possível extrair o áudio",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao extrair áudio\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro na extração de áudio TikTok: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado na extração de áudio\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_video_info(self, url):
        """Obtém informações do vídeo TikTok."""
        try:
            command = [
                'yt-dlp',
                '--dump-json',
                '--no-playlist',
                url
            ]
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                import json
                info = json.loads(stdout.decode())
                return {
                    'title': info.get('title', 'Sem título'),
                    'uploader': info.get('uploader', 'Desconhecido'),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'description': info.get('description', ''),
                    'upload_date': info.get('upload_date', '')
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do TikTok: {e}")
            return None

# Instância global do downloader
tiktok_downloader = TikTokDownloader()

# Funções de conveniência para uso externo
async def download_tiktok_video(update, context, url, quality='best'):
    """Função de conveniência para download de vídeo TikTok."""
    return await tiktok_downloader.download_video(update, context, url, quality)

async def download_tiktok_audio(update, context, url):
    """Função de conveniência para download de áudio TikTok."""
    return await tiktok_downloader.download_audio(update, context, url)

def is_tiktok_url(url):
    """Função de conveniência para verificar URL TikTok."""
    return tiktok_downloader.is_tiktok_url(url)

async def get_tiktok_info(url):
    """Função de conveniência para obter informações do TikTok."""
    return await tiktok_downloader.get_video_info(url)