import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, is_good_quality_image
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class PinterestDownloader:
    """Downloader específico para Pinterest com suporte a imagens e vídeos."""
    
    def __init__(self):
        self.platform = "Pinterest"
        self.supported_domains = [
            'pinterest.com',
            'pin.it',
            'br.pinterest.com',
            'm.pinterest.com',
            'www.pinterest.com'
        ]
    
    def is_pinterest_url(self, url):
        """Verifica se a URL é do Pinterest."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    async def download_pin(self, update, context, url):
        """Baixa pin do Pinterest (imagem ou vídeo)."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📌 Iniciando download do Pinterest\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_pinterest_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para Pinterest
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--write-thumbnail',
                '--write-description',
                '--write-info-json',
                '--output', output_template,
                '--no-playlist',
                '--extract-flat', 'false',
                url
            ]
            
            logger.info(f"Executando comando Pinterest: {' '.join(command)}")
            
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
                    "📌 Download concluído! Processando mídia...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_pinterest_"):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    # Separa vídeos e imagens
                    videos = [f for f in downloaded_files if f.endswith(('.mp4', '.webm', '.mkv'))]
                    images = [f for f in downloaded_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                    
                    # Envia vídeos
                    for video_file in videos:
                        try:
                            await send_video_with_fallback(
                                chat_id, video_file, context,
                                f"📌 Pinterest Video\n\n📎 {url[:50]}..."
                            )
                            os.remove(video_file)
                            logger.info(f"Vídeo Pinterest enviado e removido: {video_file}")
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo Pinterest {video_file}: {e}")
                    
                    # Envia imagens (apenas as de boa qualidade)
                    for image_file in images:
                        try:
                            if is_good_quality_image(image_file):
                                with open(image_file, 'rb') as img:
                                    await context.bot.send_photo(
                                        chat_id,
                                        photo=img,
                                        caption=f"📌 Pinterest Image\n\n📎 {url[:50]}..."
                                    )
                                os.remove(image_file)
                                logger.info(f"Imagem Pinterest enviada e removida: {image_file}")
                            else:
                                logger.info(f"Imagem de baixa qualidade ignorada: {image_file}")
                                os.remove(image_file)
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem Pinterest {image_file}: {e}")
                    
                    # Remove outros arquivos temporários
                    for file in downloaded_files:
                        try:
                            if os.path.exists(file):
                                os.remove(file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ Pinterest baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum arquivo encontrado\n\n💡 Verifique se o pin ainda está disponível",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para Pinterest: {error_message}")
                
                # Verifica erros específicos do Pinterest
                if 'private' in error_message.lower():
                    error_msg = "❌ Pin privado\n\n💡 Apenas pins públicos podem ser baixados"
                elif 'not found' in error_message.lower():
                    error_msg = "❌ Pin não encontrado\n\n💡 O pin pode ter sido deletado"
                elif 'rate limit' in error_message.lower():
                    error_msg = "❌ Limite de requisições atingido\n\n💡 Tente novamente em alguns minutos"
                else:
                    error_msg = f"❌ Erro ao baixar do Pinterest\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download Pinterest: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_board(self, update, context, board_url, limit=10):
        """Baixa múltiplos pins de um board do Pinterest."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"📌 Baixando board Pinterest\n\n📎 {board_url[:50]}...\n\n⚠️ Limite: {limit} pins",
                'downloading', 0
            )
            
            # Template de saída para board
            output_template = f"{chat_id}_{message_id}_pinterest_board_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando para baixar board completo
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--write-info-json',
                '--yes-playlist',
                board_url
            ]
            
            logger.info(f"Executando comando board Pinterest: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                board_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_pinterest_board_"):
                        board_files.append(file)
                
                if board_files:
                    await send_progress_message(
                        context, chat_id,
                        f"📌 {len(board_files)} pins baixados! Enviando...",
                        'processing', 50
                    )
                    
                    # Separa e envia arquivos
                    videos = [f for f in board_files if f.endswith(('.mp4', '.webm', '.mkv'))]
                    images = [f for f in board_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                    
                    sent_count = 0
                    
                    # Envia vídeos
                    for i, video_file in enumerate(videos, 1):
                        try:
                            await send_video_with_fallback(
                                chat_id, video_file, context,
                                f"📌 Board Video {i}/{len(videos)}\n\n📎 {board_url[:50]}..."
                            )
                            os.remove(video_file)
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo do board {video_file}: {e}")
                        
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
                                    caption=f"📌 Board Image {i}/{len(good_images)}\n\n📎 {board_url[:50]}..."
                                )
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem do board {image_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(good_images):
                            await asyncio.sleep(1)
                    
                    # Remove todos os arquivos temporários
                    for file in board_files:
                        try:
                            if os.path.exists(file):
                                os.remove(file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ Board Pinterest baixado!\n\n📊 {sent_count} arquivos enviados",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum pin encontrado no board\n\n💡 O board pode estar vazio ou privado",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar board\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de board Pinterest: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download de board\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def search_pins(self, update, context, search_term, limit=5):
        """Busca pins por termo de pesquisa."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🔍 Buscando pins: '{search_term}'\n\n⚠️ Limite: {limit} resultados",
                'downloading', 0
            )
            
            # Template de saída para busca
            output_template = f"{chat_id}_{message_id}_pinterest_search_%(playlist_index)s_%(title)s.%(ext)s"
            
            # URL de busca do Pinterest
            search_url = f"https://www.pinterest.com/search/pins/?q={search_term.replace(' ', '%20')}"
            
            # Comando para buscar pins
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--yes-playlist',
                search_url
            ]
            
            logger.info(f"Executando busca Pinterest: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                search_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_pinterest_search_"):
                        search_files.append(file)
                
                if search_files:
                    await send_progress_message(
                        context, chat_id,
                        f"🔍 {len(search_files)} pins encontrados! Enviando...",
                        'processing', 50
                    )
                    
                    # Separa e envia arquivos
                    videos = [f for f in search_files if f.endswith(('.mp4', '.webm', '.mkv'))]
                    images = [f for f in search_files if f.endswith(('.jpg', '.jpeg', '.png', '.webp'))]
                    
                    sent_count = 0
                    
                    # Envia vídeos
                    for video_file in videos:
                        try:
                            await send_video_with_fallback(
                                chat_id, video_file, context,
                                f"🔍 Busca: '{search_term}'\n\n📌 Pinterest Video"
                            )
                            os.remove(video_file)
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Erro ao enviar vídeo da busca {video_file}: {e}")
                    
                    # Envia imagens (apenas as de boa qualidade)
                    good_images = [img for img in images if is_good_quality_image(img)]
                    
                    for image_file in good_images:
                        try:
                            with open(image_file, 'rb') as img:
                                await context.bot.send_photo(
                                    chat_id,
                                    photo=img,
                                    caption=f"🔍 Busca: '{search_term}'\n\n📌 Pinterest Image"
                                )
                            sent_count += 1
                        except Exception as e:
                            logger.error(f"Erro ao enviar imagem da busca {image_file}: {e}")
                    
                    # Remove todos os arquivos temporários
                    for file in search_files:
                        try:
                            if os.path.exists(file):
                                os.remove(file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ Busca concluída!\n\n📊 {sent_count} pins enviados",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        f"❌ Nenhum pin encontrado para '{search_term}'",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro na busca\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro na busca Pinterest: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado na busca\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_pin_info(self, url):
        """Obtém informações do pin Pinterest."""
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
                    'description': info.get('description', ''),
                    'upload_date': info.get('upload_date', ''),
                    'width': info.get('width', 0),
                    'height': info.get('height', 0),
                    'filesize': info.get('filesize', 0),
                    'ext': info.get('ext', ''),
                    'board': info.get('playlist_title', 'Desconhecido')
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do Pinterest: {e}")
            return None

# Instância global do downloader
pinterest_downloader = PinterestDownloader()

# Funções de conveniência para uso externo
async def download_pinterest_pin(update, context, url):
    """Função de conveniência para download de pin Pinterest."""
    return await pinterest_downloader.download_pin(update, context, url)

async def download_pinterest_board(update, context, board_url, limit=10):
    """Função de conveniência para download de board Pinterest."""
    return await pinterest_downloader.download_board(update, context, board_url, limit)

async def search_pinterest_pins(update, context, search_term, limit=5):
    """Função de conveniência para buscar pins Pinterest."""
    return await pinterest_downloader.search_pins(update, context, search_term, limit)

def is_pinterest_url(url):
    """Função de conveniência para verificar URL Pinterest."""
    return pinterest_downloader.is_pinterest_url(url)

async def get_pinterest_pin_info(url):
    """Função de conveniência para obter informações do pin Pinterest."""
    return await pinterest_downloader.get_pin_info(url)