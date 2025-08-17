import logging
import os
import asyncio
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from datetime import datetime
from utils import send_progress_message, get_status_emoji

# Configura o logger
logger = logging.getLogger(__name__)

class WatermarkProcessor:
    """Classe para processar marca d'água em imagens."""
    
    def __init__(self):
        self.default_watermark_text = "@SeuBot"
        self.default_opacity = 0.7
        self.default_position = "bottom_right"
        self.default_font_size = 36
        
    def add_text_watermark(self, image_path, watermark_text=None, position=None, 
                          opacity=None, font_size=None, output_path=None):
        """Adiciona marca d'água de texto à imagem."""
        try:
            # Parâmetros padrão
            watermark_text = watermark_text or self.default_watermark_text
            position = position or self.default_position
            opacity = opacity or self.default_opacity
            font_size = font_size or self.default_font_size
            
            # Abre a imagem
            with Image.open(image_path) as img:
                # Converte para RGBA se necessário
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Cria uma camada transparente para a marca d'água
                watermark_layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
                draw = ImageDraw.Draw(watermark_layer)
                
                # Tenta carregar uma fonte
                try:
                    # Tenta fontes do sistema Windows
                    font_paths = [
                        "C:/Windows/Fonts/arial.ttf",
                        "C:/Windows/Fonts/calibri.ttf",
                        "C:/Windows/Fonts/tahoma.ttf"
                    ]
                    font = None
                    for font_path in font_paths:
                        if os.path.exists(font_path):
                            font = ImageFont.truetype(font_path, font_size)
                            break
                    
                    if not font:
                        font = ImageFont.load_default()
                        logger.warning("Usando fonte padrão para marca d'água")
                        
                except Exception as e:
                    font = ImageFont.load_default()
                    logger.warning(f"Erro ao carregar fonte: {e}")
                
                # Calcula o tamanho do texto
                bbox = draw.textbbox((0, 0), watermark_text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                
                # Calcula a posição baseada no parâmetro
                img_width, img_height = img.size
                margin = 20
                
                positions = {
                    'top_left': (margin, margin),
                    'top_right': (img_width - text_width - margin, margin),
                    'bottom_left': (margin, img_height - text_height - margin),
                    'bottom_right': (img_width - text_width - margin, img_height - text_height - margin),
                    'center': ((img_width - text_width) // 2, (img_height - text_height) // 2)
                }
                
                x, y = positions.get(position, positions['bottom_right'])
                
                # Calcula a cor com opacidade
                alpha = int(255 * opacity)
                text_color = (255, 255, 255, alpha)  # Branco com transparência
                shadow_color = (0, 0, 0, alpha // 2)  # Sombra preta
                
                # Adiciona sombra para melhor legibilidade
                draw.text((x + 2, y + 2), watermark_text, font=font, fill=shadow_color)
                # Adiciona o texto principal
                draw.text((x, y), watermark_text, font=font, fill=text_color)
                
                # Combina a imagem original com a marca d'água
                watermarked = Image.alpha_composite(img, watermark_layer)
                
                # Converte de volta para RGB se necessário
                if watermarked.mode == 'RGBA':
                    # Cria um fundo branco
                    background = Image.new('RGB', watermarked.size, (255, 255, 255))
                    background.paste(watermarked, mask=watermarked.split()[-1])
                    watermarked = background
                
                # Define o caminho de saída
                if not output_path:
                    name, ext = os.path.splitext(image_path)
                    output_path = f"{name}_watermarked{ext}"
                
                # Salva a imagem
                watermarked.save(output_path, quality=95, optimize=True)
                logger.info(f"Marca d'água aplicada: {output_path}")
                
                return output_path
                
        except Exception as e:
            logger.error(f"Erro ao aplicar marca d'água: {e}")
            raise
    
    def add_logo_watermark(self, image_path, logo_path, position=None, 
                          opacity=None, scale=0.1, output_path=None):
        """Adiciona marca d'água de logo/imagem à imagem."""
        try:
            position = position or self.default_position
            opacity = opacity or self.default_opacity
            
            # Abre a imagem principal
            with Image.open(image_path) as img:
                # Abre o logo
                with Image.open(logo_path) as logo:
                    # Converte para RGBA se necessário
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    if logo.mode != 'RGBA':
                        logo = logo.convert('RGBA')
                    
                    # Redimensiona o logo baseado na escala
                    img_width, img_height = img.size
                    logo_width = int(img_width * scale)
                    logo_height = int(logo.size[1] * (logo_width / logo.size[0]))
                    logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
                    
                    # Aplica opacidade ao logo
                    if opacity < 1.0:
                        alpha = logo.split()[-1]
                        alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
                        logo.putalpha(alpha)
                    
                    # Calcula a posição
                    margin = 20
                    positions = {
                        'top_left': (margin, margin),
                        'top_right': (img_width - logo_width - margin, margin),
                        'bottom_left': (margin, img_height - logo_height - margin),
                        'bottom_right': (img_width - logo_width - margin, img_height - logo_height - margin),
                        'center': ((img_width - logo_width) // 2, (img_height - logo_height) // 2)
                    }
                    
                    x, y = positions.get(position, positions['bottom_right'])
                    
                    # Aplica o logo
                    img.paste(logo, (x, y), logo)
                    
                    # Converte de volta para RGB se necessário
                    if img.mode == 'RGBA':
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        background.paste(img, mask=img.split()[-1])
                        img = background
                    
                    # Define o caminho de saída
                    if not output_path:
                        name, ext = os.path.splitext(image_path)
                        output_path = f"{name}_watermarked{ext}"
                    
                    # Salva a imagem
                    img.save(output_path, quality=95, optimize=True)
                    logger.info(f"Logo aplicado como marca d'água: {output_path}")
                    
                    return output_path
                    
        except Exception as e:
            logger.error(f"Erro ao aplicar logo como marca d'água: {e}")
            raise
    
    async def process_watermark_request(self, context, chat_id, image_path, 
                                      watermark_config=None):
        """Processa uma solicitação de marca d'água."""
        try:
            await send_progress_message(
                context, chat_id,
                "🎨 Aplicando marca d'água...",
                'processing', 25
            )
            
            # Configuração padrão
            config = watermark_config or {}
            watermark_type = config.get('type', 'text')
            
            if watermark_type == 'text':
                output_path = self.add_text_watermark(
                    image_path,
                    watermark_text=config.get('text'),
                    position=config.get('position'),
                    opacity=config.get('opacity'),
                    font_size=config.get('font_size')
                )
            elif watermark_type == 'logo' and config.get('logo_path'):
                output_path = self.add_logo_watermark(
                    image_path,
                    logo_path=config['logo_path'],
                    position=config.get('position'),
                    opacity=config.get('opacity'),
                    scale=config.get('scale', 0.1)
                )
            else:
                # Padrão: marca d'água de texto
                output_path = self.add_text_watermark(image_path)
            
            await send_progress_message(
                context, chat_id,
                "📤 Enviando imagem com marca d'água...",
                'uploading', 75
            )
            
            # Envia a imagem processada
            with open(output_path, 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption="✨ Imagem com marca d'água aplicada!"
                )
            
            await send_progress_message(
                context, chat_id,
                "✅ Marca d'água aplicada com sucesso!",
                'completed', 100
            )
            
            # Remove arquivos temporários
            try:
                os.remove(image_path)
                os.remove(output_path)
            except Exception as e:
                logger.warning(f"Erro ao remover arquivos temporários: {e}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Erro no processamento de marca d'água: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro ao aplicar marca d'água: {str(e)[:100]}...",
                'error'
            )
            raise

# Instância global do processador
watermark_processor = WatermarkProcessor()

# Funções auxiliares para uso no bot
async def apply_text_watermark(context, chat_id, image_path, text=None, 
                              position="bottom_right", opacity=0.7):
    """Aplica marca d'água de texto (função simplificada)."""
    config = {
        'type': 'text',
        'text': text,
        'position': position,
        'opacity': opacity
    }
    return await watermark_processor.process_watermark_request(
        context, chat_id, image_path, config
    )

async def apply_logo_watermark(context, chat_id, image_path, logo_path, 
                              position="bottom_right", opacity=0.7, scale=0.1):
    """Aplica marca d'água de logo (função simplificada)."""
    config = {
        'type': 'logo',
        'logo_path': logo_path,
        'position': position,
        'opacity': opacity,
        'scale': scale
    }
    return await watermark_processor.process_watermark_request(
        context, chat_id, image_path, config
    )