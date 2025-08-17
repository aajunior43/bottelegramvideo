import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, check_ffmpeg
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class TwitchDownloader:
    """Downloader específico para Twitch com suporte a clipes de streams."""
    
    def __init__(self):
        self.platform = "Twitch"
        self.supported_domains = [
            'twitch.tv',
            'clips.twitch.tv',
            'm.twitch.tv',
            'www.twitch.tv'
        ]
    
    def is_twitch_url(self, url):
        """Verifica se a URL é do Twitch."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    def is_twitch_clip(self, url):
        """Verifica se a URL é de um clipe do Twitch."""
        url_lower = url.lower()
        return 'clip' in url_lower or 'clips.twitch.tv' in url_lower
    
    async def download_clip(self, update, context, url, quality='best'):
        """Baixa clipe do Twitch."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎮 Iniciando download do clipe Twitch\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_twitch_clip_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para clipes Twitch
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
            
            logger.info(f"Executando comando Twitch clip: {' '.join(command)}")
            
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
                    "🎮 Download concluído! Processando clipe...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitch_clip_") and file.endswith('.mp4'):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    video_file = downloaded_files[0]
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, video_file, context,
                        f"🎮 Twitch Clip\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_twitch_clip_"):
                            try:
                                os.remove(file)
                                logger.info(f"Arquivo removido: {file}")
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Clipe Twitch baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado\n\n💡 Verifique se o clipe ainda está disponível",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para Twitch clip: {error_message}")
                
                # Verifica erros específicos do Twitch
                if 'private' in error_message.lower():
                    error_msg = "❌ Clipe privado ou removido\n\n💡 Apenas clipes públicos podem ser baixados"
                elif 'not found' in error_message.lower():
                    error_msg = "❌ Clipe não encontrado\n\n💡 O clipe pode ter sido deletado"
                elif 'subscriber' in error_message.lower():
                    error_msg = "❌ Conteúdo para assinantes\n\n💡 Não é possível baixar conteúdo restrito"
                else:
                    error_msg = f"❌ Erro ao baixar clipe Twitch\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download Twitch clip: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_vod_segment(self, update, context, url, start_time=None, duration=None):
        """Baixa segmento de VOD (Video On Demand) do Twitch."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            time_info = ""
            if start_time and duration:
                time_info = f"\n\n⏰ Início: {start_time}\n⏱️ Duração: {duration}"
            
            await send_progress_message(
                context, chat_id,
                f"📺 Baixando VOD Twitch{time_info}\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_twitch_vod_%(title)s.%(ext)s"
            
            # Comando base
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--no-playlist'
            ]
            
            # Adiciona parâmetros de tempo se especificados
            if start_time:
                command.extend(['--download-sections', f'*{start_time}-{start_time}+{duration if duration else "30:00"}'])
            
            command.append(url)
            
            logger.info(f"Executando comando Twitch VOD: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                vod_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitch_vod_") and file.endswith('.mp4'):
                        vod_files.append(file)
                
                if vod_files:
                    vod_file = vod_files[0]
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, vod_file, context,
                        f"📺 Twitch VOD{time_info}\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivo temporário
                    os.remove(vod_file)
                    logger.info(f"VOD Twitch enviado e removido: {vod_file}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ VOD Twitch baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo VOD encontrado",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar VOD\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de VOD Twitch: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de VOD\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_channel_clips(self, update, context, channel_url, limit=5):
        """Baixa múltiplos clipes de um canal Twitch."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎮 Baixando clipes do canal\n\n📎 {channel_url[:50]}...\n\n⚠️ Limite: {limit} clipes",
                'downloading', 0
            )
            
            # Template de saída para múltiplos clipes
            output_template = f"{chat_id}_{message_id}_twitch_clips_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando para baixar clipes de um canal
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--write-info-json',
                f"{channel_url}/clips"
            ]
            
            logger.info(f"Executando comando clipes canal: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                clips_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_twitch_clips_") and file.endswith('.mp4'):
                        clips_files.append(file)
                
                if clips_files:
                    await send_progress_message(
                        context, chat_id,
                        f"🎮 {len(clips_files)} clipes baixados! Enviando...",
                        'processing', 50
                    )
                    
                    # Envia cada clipe
                    for i, clip_file in enumerate(sorted(clips_files), 1):
                        await send_video_with_fallback(
                            chat_id, clip_file, context,
                            f"🎮 Clipe {i}/{len(clips_files)}\n\n📎 {channel_url[:50]}..."
                        )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(clip_file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {clip_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(clips_files):
                            await asyncio.sleep(2)
                    
                    # Remove outros arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_twitch_clips_"):
                            try:
                                os.remove(file)
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ {len(clips_files)} clipes baixados com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum clipe encontrado\n\n💡 O canal pode não ter clipes públicos",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar clipes do canal\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de clipes do canal: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de clipes\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_clip_info(self, url):
        """Obtém informações do clipe Twitch."""
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
                    'description': info.get('description', ''),
                    'upload_date': info.get('upload_date', ''),
                    'game': info.get('game', 'Desconhecido'),
                    'creator': info.get('creator', 'Desconhecido'),
                    'clip_id': info.get('id', '')
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do clipe Twitch: {e}")
            return None
    
    async def search_clips(self, game_name, limit=5):
        """Busca clipes populares de um jogo específico."""
        try:
            # Esta funcionalidade requer API do Twitch
            # Por enquanto, retorna None indicando que não está implementada
            logger.info(f"Busca de clipes por jogo '{game_name}' não implementada ainda")
            return None
                
        except Exception as e:
            logger.error(f"Erro na busca de clipes: {e}")
            return None

# Instância global do downloader
twitch_downloader = TwitchDownloader()

# Funções de conveniência para uso externo
async def download_twitch_clip(update, context, url, quality='best'):
    """Função de conveniência para download de clipe Twitch."""
    return await twitch_downloader.download_clip(update, context, url, quality)

async def download_twitch_vod(update, context, url, start_time=None, duration=None):
    """Função de conveniência para download de VOD Twitch."""
    return await twitch_downloader.download_vod_segment(update, context, url, start_time, duration)

async def download_channel_clips(update, context, channel_url, limit=5):
    """Função de conveniência para download de clipes de canal."""
    return await twitch_downloader.download_channel_clips(update, context, channel_url, limit)

def is_twitch_url(url):
    """Função de conveniência para verificar URL Twitch."""
    return twitch_downloader.is_twitch_url(url)

def is_twitch_clip_url(url):
    """Função de conveniência para verificar URL de clipe Twitch."""
    return twitch_downloader.is_twitch_clip(url)

async def get_twitch_clip_info(url):
    """Função de conveniência para obter informações do clipe Twitch."""
    return await twitch_downloader.get_clip_info(url)