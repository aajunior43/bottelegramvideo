import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, check_ffmpeg
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class YouTubeShortsDownloader:
    """Downloader específico para YouTube Shorts com otimizações para formato vertical."""
    
    def __init__(self):
        self.platform = "YouTube Shorts"
        self.supported_patterns = [
            '/shorts/',
            'youtube.com/shorts',
            'youtu.be/shorts',
            'm.youtube.com/shorts'
        ]
    
    def is_youtube_shorts_url(self, url):
        """Verifica se a URL é de um YouTube Short."""
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in self.supported_patterns)
    
    def is_vertical_video(self, url):
        """Verifica se é um vídeo vertical (pode ser Short mesmo sem /shorts/ na URL)."""
        # Alguns Shorts podem não ter /shorts/ na URL mas são verticais
        return 'youtube.com' in url.lower() or 'youtu.be' in url.lower()
    
    async def download_short(self, update, context, url, quality='best'):
        """Baixa YouTube Short com otimizações para formato vertical."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📱 Iniciando download do YouTube Short\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_ytshorts_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para Shorts (formato vertical)
            command = [
                'yt-dlp',
                '--format', f'{quality}[height>=720][width<height]/best[height>=720]/best',  # Prioriza vertical
                '--write-thumbnail',
                '--write-description',
                '--write-info-json',
                '--merge-output-format', 'mp4',
                '--output', output_template,
                '--no-playlist',
                '--extract-flat', 'false',
                '--embed-chapters',
                '--embed-metadata',
                url
            ]
            
            logger.info(f"Executando comando YouTube Shorts: {' '.join(command)}")
            
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
                    "📱 Download concluído! Processando Short...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_ytshorts_") and file.endswith('.mp4'):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    video_file = downloaded_files[0]
                    
                    # Verifica se é realmente vertical e otimiza se necessário
                    await self._optimize_vertical_video(video_file, chat_id, message_id)
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, video_file, context,
                        f"📱 YouTube Short\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_ytshorts_"):
                            try:
                                os.remove(file)
                                logger.info(f"Arquivo removido: {file}")
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ YouTube Short baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado\n\n💡 Verifique se o Short ainda está disponível",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para YouTube Shorts: {error_message}")
                
                # Verifica erros específicos do YouTube
                if 'private' in error_message.lower():
                    error_msg = "❌ Vídeo privado\n\n💡 Apenas vídeos públicos podem ser baixados"
                elif 'not available' in error_message.lower():
                    error_msg = "❌ Short não disponível\n\n💡 O vídeo pode ter sido removido ou estar restrito"
                elif 'age-restricted' in error_message.lower():
                    error_msg = "❌ Conteúdo com restrição de idade\n\n💡 Não é possível baixar este tipo de conteúdo"
                else:
                    error_msg = f"❌ Erro ao baixar YouTube Short\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download YouTube Shorts: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def _optimize_vertical_video(self, video_file, chat_id, message_id):
        """Otimiza vídeo vertical para melhor qualidade no Telegram."""
        try:
            # Verifica dimensões do vídeo
            probe_cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', video_file
            ]
            
            process = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                import json
                probe_data = json.loads(stdout.decode())
                
                for stream in probe_data.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = int(stream.get('width', 0))
                        height = int(stream.get('height', 0))
                        
                        # Se é vertical (altura > largura) e muito grande, redimensiona
                        if height > width and height > 1920:
                            optimized_file = f"{chat_id}_{message_id}_ytshorts_optimized.mp4"
                            
                            # Comando para otimizar vídeo vertical
                            optimize_cmd = [
                                'ffmpeg', '-i', video_file,
                                '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2',
                                '-c:v', 'libx264', '-preset', 'fast',
                                '-c:a', 'aac', '-b:a', '128k',
                                '-y', optimized_file
                            ]
                            
                            opt_process = await asyncio.create_subprocess_exec(
                                *optimize_cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE
                            )
                            
                            await opt_process.communicate()
                            
                            if opt_process.returncode == 0 and os.path.exists(optimized_file):
                                # Substitui o arquivo original pelo otimizado
                                os.replace(optimized_file, video_file)
                                logger.info(f"Vídeo vertical otimizado: {video_file}")
                        break
                        
        except Exception as e:
            logger.warning(f"Erro na otimização do vídeo vertical: {e}")
    
    async def download_shorts_playlist(self, update, context, channel_url, limit=10):
        """Baixa múltiplos Shorts de um canal."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📱 Baixando Shorts do canal\n\n📎 {channel_url[:50]}...\n\n⚠️ Limite: {limit} vídeos",
                'downloading', 0
            )
            
            # Template de saída para playlist
            output_template = f"{chat_id}_{message_id}_ytshorts_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando para baixar Shorts de um canal
            command = [
                'yt-dlp',
                '--format', 'best[height>=720][width<height]/best[height>=720]/best',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--match-filter', 'duration < 60',  # Apenas vídeos curtos (Shorts)
                '--write-info-json',
                channel_url + '/shorts'
            ]
            
            logger.info(f"Executando comando playlist Shorts: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                shorts_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_ytshorts_") and file.endswith('.mp4'):
                        shorts_files.append(file)
                
                if shorts_files:
                    await send_progress_message(
                        context, chat_id,
                        f"📱 {len(shorts_files)} Shorts baixados! Enviando...",
                        'processing', 50
                    )
                    
                    # Envia cada Short
                    for i, short_file in enumerate(sorted(shorts_files), 1):
                        await send_video_with_fallback(
                            chat_id, short_file, context,
                            f"📱 Short {i}/{len(shorts_files)}\n\n📎 {channel_url[:50]}..."
                        )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(short_file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {short_file}: {e}")
                        
                        # Pausa entre envios para evitar spam
                        if i < len(shorts_files):
                            await asyncio.sleep(2)
                    
                    # Remove outros arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_ytshorts_"):
                            try:
                                os.remove(file)
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ {len(shorts_files)} Shorts baixados com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum Short encontrado\n\n💡 O canal pode não ter Shorts ou eles podem estar privados",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar Shorts do canal\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de playlist Shorts: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de playlist\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_shorts_info(self, url):
        """Obtém informações do YouTube Short."""
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
                    'upload_date': info.get('upload_date', ''),
                    'width': info.get('width', 0),
                    'height': info.get('height', 0),
                    'is_vertical': info.get('height', 0) > info.get('width', 0)
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do YouTube Shorts: {e}")
            return None

# Instância global do downloader
youtube_shorts_downloader = YouTubeShortsDownloader()

# Funções de conveniência para uso externo
async def download_youtube_short(update, context, url, quality='best'):
    """Função de conveniência para download de YouTube Short."""
    return await youtube_shorts_downloader.download_short(update, context, url, quality)

async def download_shorts_from_channel(update, context, channel_url, limit=10):
    """Função de conveniência para download de Shorts de um canal."""
    return await youtube_shorts_downloader.download_shorts_playlist(update, context, channel_url, limit)

def is_youtube_shorts_url(url):
    """Função de conveniência para verificar URL de YouTube Shorts."""
    return youtube_shorts_downloader.is_youtube_shorts_url(url)

def is_vertical_youtube_video(url):
    """Função de conveniência para verificar se é vídeo vertical do YouTube."""
    return youtube_shorts_downloader.is_vertical_video(url)

async def get_youtube_shorts_info(url):
    """Função de conveniência para obter informações do YouTube Shorts."""
    return await youtube_shorts_downloader.get_shorts_info(url)