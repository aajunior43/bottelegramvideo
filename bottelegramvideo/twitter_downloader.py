import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, check_ffmpeg
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class TwitterDownloader:
    """Downloader específico para Twitter/X com suporte a vídeos e GIFs."""
    
    def __init__(self):
        self.platform = "Twitter/X"
        self.supported_domains = [
            'twitter.com',
            'x.com',
            't.co',
            'mobile.twitter.com',
            'm.twitter.com'
        ]
    
    def is_twitter_url(self, url):
        """Verifica se a URL é do Twitter/X."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    async def download_video(self, update, context, url, quality='best'):
        """Baixa vídeo do Twitter/X."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🐦 Iniciando download do Twitter/X\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_twitter_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para Twitter
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
                '--cookies-from-browser', 'chrome',  # Para acessar conteúdo que requer login
                url
            ]
            
            logger.info(f"Executando comando Twitter: {' '.join(command)}")
            
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
                    "🐦 Download concluído! Processando arquivo...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitter_") and file.endswith(('.mp4', '.gif', '.webm')):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    for video_file in downloaded_files:
                        # Verifica se é GIF
                        if video_file.endswith('.gif'):
                            # Envia como animação
                            with open(video_file, 'rb') as gif:
                                await context.bot.send_animation(
                                    chat_id,
                                    animation=gif,
                                    caption=f"🐦 Twitter GIF\n\n📎 {url[:50]}..."
                                )
                        else:
                            # Envia como vídeo
                            await send_video_with_fallback(
                                chat_id, video_file, context,
                                f"🐦 Twitter Video\n\n📎 {url[:50]}..."
                            )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(video_file)
                            logger.info(f"Arquivo removido: {video_file}")
                        except Exception as e:
                            logger.warning(f"Erro ao remover {video_file}: {e}")
                    
                    # Remove outros arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_twitter_"):
                            try:
                                os.remove(file)
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Twitter/X baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado\n\n💡 Verifique se o tweet ainda está disponível ou se contém mídia",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para Twitter: {error_message}")
                
                # Verifica erros específicos do Twitter
                if 'private' in error_message.lower():
                    error_msg = "❌ Tweet privado ou protegido\n\n💡 Apenas tweets públicos podem ser baixados"
                elif 'not found' in error_message.lower():
                    error_msg = "❌ Tweet não encontrado\n\n💡 O tweet pode ter sido deletado"
                elif 'rate limit' in error_message.lower():
                    error_msg = "❌ Limite de requisições atingido\n\n💡 Tente novamente em alguns minutos"
                else:
                    error_msg = f"❌ Erro ao baixar do Twitter/X\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download Twitter: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_gif(self, update, context, url):
        """Baixa GIF do Twitter/X especificamente."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎭 Baixando GIF do Twitter/X\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída para GIF
            output_template = f"{chat_id}_{message_id}_twitter_gif_%(title)s.%(ext)s"
            
            # Comando específico para GIFs
            command = [
                'yt-dlp',
                '--format', 'best[ext=gif]/best',
                '--output', output_template,
                '--no-playlist',
                url
            ]
            
            logger.info(f"Executando comando GIF Twitter: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos GIF
                gif_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitter_gif_"):
                        gif_files.append(file)
                
                if gif_files:
                    gif_file = gif_files[0]
                    
                    # Envia o GIF
                    with open(gif_file, 'rb') as gif:
                        await context.bot.send_animation(
                            chat_id,
                            animation=gif,
                            caption=f"🎭 Twitter GIF\n\n📎 {url[:50]}..."
                        )
                    
                    # Remove arquivo temporário
                    os.remove(gif_file)
                    logger.info(f"GIF Twitter enviado e removido: {gif_file}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ GIF do Twitter baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum GIF encontrado\n\n💡 O tweet pode não conter GIFs",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar GIF\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de GIF Twitter: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de GIF\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_thread(self, update, context, url):
        """Baixa thread completa do Twitter/X."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🧵 Baixando thread do Twitter/X\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída para thread
            output_template = f"{chat_id}_{message_id}_twitter_thread_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando para thread completa
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--yes-playlist',  # Baixa toda a thread
                '--write-info-json',
                url
            ]
            
            logger.info(f"Executando comando thread Twitter: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos da thread
                thread_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitter_thread_"):
                        thread_files.append(file)
                
                if thread_files:
                    await send_progress_message(
                        context, chat_id,
                        f"🧵 Thread baixada! Enviando {len(thread_files)} arquivos...",
                        'processing', 50
                    )
                    
                    # Envia cada arquivo da thread
                    for i, thread_file in enumerate(sorted(thread_files), 1):
                        if thread_file.endswith(('.mp4', '.webm', '.gif')):
                            if thread_file.endswith('.gif'):
                                with open(thread_file, 'rb') as gif:
                                    await context.bot.send_animation(
                                        chat_id,
                                        animation=gif,
                                        caption=f"🧵 Thread {i}/{len(thread_files)}\n\n📎 {url[:50]}..."
                                    )
                            else:
                                await send_video_with_fallback(
                                    chat_id, thread_file, context,
                                    f"🧵 Thread {i}/{len(thread_files)}\n\n📎 {url[:50]}..."
                                )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(thread_file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {thread_file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Thread do Twitter baixada com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado na thread",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar thread\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de thread Twitter: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de thread\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_tweet_info(self, url):
        """Obtém informações do tweet."""
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
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'repost_count': info.get('repost_count', 0),
                    'like_count': info.get('like_count', 0),
                    'comment_count': info.get('comment_count', 0),
                    'view_count': info.get('view_count', 0)
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do Twitter: {e}")
            return None

# Instância global do downloader
twitter_downloader = TwitterDownloader()

# Funções de conveniência para uso externo
async def download_twitter_video(update, context, url, quality='best'):
    """Função de conveniência para download de vídeo Twitter."""
    return await twitter_downloader.download_video(update, context, url, quality)

async def download_twitter_gif(update, context, url):
    """Função de conveniência para download de GIF Twitter."""
    return await twitter_downloader.download_gif(update, context, url)

async def download_twitter_thread(update, context, url):
    """Função de conveniência para download de thread Twitter."""
    return await twitter_downloader.download_thread(update, context, url)

def is_twitter_url(url):
    """Função de conveniência para verificar URL Twitter."""
    return twitter_downloader.is_twitter_url(url)

async def get_twitter_info(url):
    """Função de conveniência para obter informações do Twitter."""
    return await twitter_downloader.get_tweet_info(url)