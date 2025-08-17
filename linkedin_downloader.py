import asyncio
import logging
import os
import subprocess
from datetime import datetime
from utils import send_progress_message, check_ffmpeg
from downloaders import send_video_with_fallback

# Configura o logger
logger = logging.getLogger(__name__)

class LinkedInDownloader:
    """Downloader específico para LinkedIn com suporte a vídeos corporativos."""
    
    def __init__(self):
        self.platform = "LinkedIn"
        self.supported_domains = [
            'linkedin.com',
            'www.linkedin.com',
            'm.linkedin.com',
            'lnkd.in'
        ]
    
    def is_linkedin_url(self, url):
        """Verifica se a URL é do LinkedIn."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)
    
    def is_linkedin_video_post(self, url):
        """Verifica se a URL é de um post com vídeo do LinkedIn."""
        url_lower = url.lower()
        return 'linkedin.com' in url_lower and ('/posts/' in url_lower or '/feed/update/' in url_lower)
    
    async def download_video_post(self, update, context, url, quality='best'):
        """Baixa vídeo de post do LinkedIn."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"💼 Iniciando download do LinkedIn\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída
            output_template = f"{chat_id}_{message_id}_linkedin_%(title)s.%(ext)s"
            
            # Comando yt-dlp otimizado para LinkedIn
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
            
            logger.info(f"Executando comando LinkedIn: {' '.join(command)}")
            
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
                    "💼 Download concluído! Processando vídeo...",
                    'processing', 75
                )
                
                # Procura por arquivos baixados
                downloaded_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_linkedin_") and file.endswith('.mp4'):
                        downloaded_files.append(file)
                
                if downloaded_files:
                    video_file = downloaded_files[0]
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, video_file, context,
                        f"💼 LinkedIn Video\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_linkedin_"):
                            try:
                                os.remove(file)
                                logger.info(f"Arquivo removido: {file}")
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ LinkedIn baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum vídeo encontrado\n\n💡 Verifique se o post contém vídeo e está público",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                logger.error(f"Erro no yt-dlp para LinkedIn: {error_message}")
                
                # Verifica erros específicos do LinkedIn
                if 'private' in error_message.lower() or 'login' in error_message.lower():
                    error_msg = "❌ Conteúdo privado ou requer login\n\n💡 Apenas posts públicos podem ser baixados"
                elif 'not found' in error_message.lower():
                    error_msg = "❌ Post não encontrado\n\n💡 O post pode ter sido deletado ou a URL está incorreta"
                elif 'rate limit' in error_message.lower():
                    error_msg = "❌ Limite de requisições atingido\n\n💡 Tente novamente em alguns minutos"
                else:
                    error_msg = f"❌ Erro ao baixar do LinkedIn\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`"
                
                await send_progress_message(
                    context, chat_id, error_msg, 'error'
                )
                
        except Exception as e:
            logger.error(f"Erro inesperado no download LinkedIn: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_learning_video(self, update, context, url):
        """Baixa vídeo do LinkedIn Learning."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🎓 Baixando vídeo LinkedIn Learning\n\n📎 {url[:50]}...",
                'downloading', 0
            )
            
            # Template de saída para Learning
            output_template = f"{chat_id}_{message_id}_linkedin_learning_%(title)s.%(ext)s"
            
            # Comando específico para LinkedIn Learning
            command = [
                'yt-dlp',
                '--format', 'best[height<=720]/best',  # Learning geralmente tem qualidade menor
                '--output', output_template,
                '--no-playlist',
                '--write-info-json',
                '--cookies-from-browser', 'chrome',  # Requer autenticação
                url
            ]
            
            logger.info(f"Executando comando LinkedIn Learning: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                learning_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_linkedin_learning_") and file.endswith('.mp4'):
                        learning_files.append(file)
                
                if learning_files:
                    learning_file = learning_files[0]
                    
                    # Envia o vídeo
                    await send_video_with_fallback(
                        chat_id, learning_file, context,
                        f"🎓 LinkedIn Learning\n\n📎 {url[:50]}..."
                    )
                    
                    # Remove arquivo temporário
                    os.remove(learning_file)
                    logger.info(f"Vídeo Learning enviado e removido: {learning_file}")
                    
                    await send_progress_message(
                        context, chat_id,
                        "✅ LinkedIn Learning baixado com sucesso!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum vídeo Learning encontrado\n\n💡 Verifique se você tem acesso ao curso",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar LinkedIn Learning\n\n💡 Pode ser necessário estar logado\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download LinkedIn Learning: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no LinkedIn Learning\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def download_company_video(self, update, context, company_url, limit=3):
        """Baixa vídeos de uma página de empresa."""
        try:
            chat_id = update.message.chat_id if hasattr(update, 'message') else update
            message_id = update.message.message_id if hasattr(update, 'message') else 0
            
            await send_progress_message(
                context, chat_id,
                f"🏢 Baixando vídeos da empresa\n\n📎 {company_url[:50]}...\n\n⚠️ Limite: {limit} vídeos",
                'downloading', 0
            )
            
            # Template de saída para empresa
            output_template = f"{chat_id}_{message_id}_linkedin_company_%(playlist_index)s_%(title)s.%(ext)s"
            
            # Comando para baixar vídeos de empresa
            command = [
                'yt-dlp',
                '--format', 'best[height<=1080]/best',
                '--output', output_template,
                '--playlist-end', str(limit),
                '--yes-playlist',
                '--write-info-json',
                '--cookies-from-browser', 'chrome',
                company_url
            ]
            
            logger.info(f"Executando comando empresa LinkedIn: {' '.join(command)}")
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                # Procura por arquivos baixados
                company_files = []
                for file in os.listdir('.'):
                    if file.startswith(f"{chat_id}_{message_id}_linkedin_company_") and file.endswith('.mp4'):
                        company_files.append(file)
                
                if company_files:
                    await send_progress_message(
                        context, chat_id,
                        f"🏢 {len(company_files)} vídeos baixados! Enviando...",
                        'processing', 50
                    )
                    
                    # Envia cada vídeo
                    for i, company_file in enumerate(sorted(company_files), 1):
                        await send_video_with_fallback(
                            chat_id, company_file, context,
                            f"🏢 Empresa {i}/{len(company_files)}\n\n📎 {company_url[:50]}..."
                        )
                        
                        # Remove arquivo temporário
                        try:
                            os.remove(company_file)
                        except Exception as e:
                            logger.warning(f"Erro ao remover {company_file}: {e}")
                        
                        # Pausa entre envios
                        if i < len(company_files):
                            await asyncio.sleep(2)
                    
                    # Remove outros arquivos temporários
                    for file in os.listdir('.'):
                        if file.startswith(f"{chat_id}_{message_id}_linkedin_company_"):
                            try:
                                os.remove(file)
                            except Exception as e:
                                logger.warning(f"Erro ao remover {file}: {e}")
                    
                    await send_progress_message(
                        context, chat_id,
                        f"✅ {len(company_files)} vídeos da empresa baixados!",
                        'completed', 100
                    )
                else:
                    await send_progress_message(
                        context, chat_id,
                        "❌ Nenhum vídeo encontrado\n\n💡 A empresa pode não ter vídeos públicos",
                        'error'
                    )
            else:
                error_message = stderr.decode('utf-8', errors='ignore')
                await send_progress_message(
                    context, chat_id,
                    f"❌ Erro ao baixar vídeos da empresa\n\nErro: `{error_message.splitlines()[-1] if error_message.splitlines() else 'Erro desconhecido'}`",
                    'error'
                )
                
        except Exception as e:
            logger.error(f"Erro no download de vídeos da empresa: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro inesperado no download da empresa\n\nDetalhes: {str(e)[:100]}...",
                'error'
            )
    
    async def get_post_info(self, url):
        """Obtém informações do post LinkedIn."""
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
                    'company': info.get('uploader', 'Desconhecido'),
                    'post_type': 'video' if info.get('duration', 0) > 0 else 'unknown'
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Erro ao obter info do LinkedIn: {e}")
            return None
    
    def get_content_type(self, url):
        """Identifica o tipo de conteúdo LinkedIn."""
        url_lower = url.lower()
        
        if 'learning.linkedin.com' in url_lower:
            return 'learning'
        elif '/company/' in url_lower:
            return 'company'
        elif '/posts/' in url_lower or '/feed/update/' in url_lower:
            return 'post'
        elif '/in/' in url_lower:
            return 'profile'
        else:
            return 'unknown'

# Instância global do downloader
linkedin_downloader = LinkedInDownloader()

# Funções de conveniência para uso externo
async def download_linkedin_video(update, context, url, quality='best'):
    """Função de conveniência para download de vídeo LinkedIn."""
    content_type = linkedin_downloader.get_content_type(url)
    
    if content_type == 'learning':
        return await linkedin_downloader.download_learning_video(update, context, url)
    elif content_type == 'company':
        return await linkedin_downloader.download_company_video(update, context, url)
    else:
        return await linkedin_downloader.download_video_post(update, context, url, quality)

async def download_linkedin_learning(update, context, url):
    """Função de conveniência para download de LinkedIn Learning."""
    return await linkedin_downloader.download_learning_video(update, context, url)

async def download_company_videos(update, context, company_url, limit=3):
    """Função de conveniência para download de vídeos de empresa."""
    return await linkedin_downloader.download_company_video(update, context, company_url, limit)

def is_linkedin_url(url):
    """Função de conveniência para verificar URL LinkedIn."""
    return linkedin_downloader.is_linkedin_url(url)

def is_linkedin_video_url(url):
    """Função de conveniência para verificar URL de vídeo LinkedIn."""
    return linkedin_downloader.is_linkedin_video_post(url)

def get_linkedin_content_type(url):
    """Função de conveniência para identificar tipo de conteúdo LinkedIn."""
    return linkedin_downloader.get_content_type(url)

async def get_linkedin_post_info(url):
    """Função de conveniência para obter informações do post LinkedIn."""
    return await linkedin_downloader.get_post_info(url)