#!/usr/bin/env python3
"""
Processador de Marca D'água Refatorado - Versão 2.1.0

Melhorias implementadas:
- Cache de fontes para melhor performance
- Processamento assíncrono otimizado
- Validação robusta de entrada
- Suporte a múltiplos formatos
- Sistema de templates
- Processamento em lote
- Configuração avançada
- Melhor tratamento de erros
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from datetime import datetime

from utils import send_progress_message, get_status_emoji


class WatermarkPosition(Enum):
    """Posições disponíveis para marca d'água."""
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    TOP_CENTER = "top_center"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_CENTER = "bottom_center"
    CENTER = "center"
    CENTER_LEFT = "center_left"
    CENTER_RIGHT = "center_right"


class WatermarkType(Enum):
    """Tipos de marca d'água suportados."""
    TEXT = "text"
    LOGO = "logo"
    COMBINED = "combined"


@dataclass
class FontConfig:
    """Configuração de fonte."""
    family: str
    size: int
    style: str = "normal"  # normal, bold, italic
    color: Tuple[int, int, int, int] = (255, 255, 255, 180)  # RGBA
    shadow_color: Tuple[int, int, int, int] = (0, 0, 0, 90)  # RGBA
    shadow_offset: Tuple[int, int] = (2, 2)
    outline_width: int = 0
    outline_color: Tuple[int, int, int, int] = (0, 0, 0, 255)


@dataclass
class WatermarkConfig:
    """Configuração completa de marca d'água."""
    type: WatermarkType = WatermarkType.TEXT
    text: str = "@SeuBot"
    position: WatermarkPosition = WatermarkPosition.BOTTOM_RIGHT
    opacity: float = 0.7
    margin: int = 20
    
    # Configurações de texto
    font_config: FontConfig = field(default_factory=FontConfig)
    
    # Configurações de logo
    logo_path: Optional[str] = None
    logo_scale: float = 0.1
    logo_opacity: float = 0.7
    
    # Configurações avançadas
    rotation: float = 0.0
    blur_radius: float = 0.0
    tile_mode: bool = False
    tile_spacing: Tuple[int, int] = (100, 100)
    
    # Configurações de saída
    output_quality: int = 95
    output_format: str = "JPEG"
    preserve_transparency: bool = False


class FontManager:
    """Gerenciador de fontes com cache."""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._font_cache: Dict[str, ImageFont.FreeTypeFont] = {}
        self._system_fonts = self._discover_system_fonts()
    
    def _discover_system_fonts(self) -> List[str]:
        """Descobre fontes disponíveis no sistema."""
        font_paths = []
        
        # Caminhos comuns de fontes
        common_paths = [
            "/System/Library/Fonts/",  # macOS
            "/usr/share/fonts/",  # Linux
            "C:/Windows/Fonts/",  # Windows
            "/usr/local/share/fonts/",  # Linux local
        ]
        
        # Fontes específicas por sistema
        font_files = {
            "arial": ["arial.ttf", "Arial.ttf", "arial.ttc"],
            "helvetica": ["helvetica.ttf", "Helvetica.ttf", "HelveticaNeue.ttc"],
            "calibri": ["calibri.ttf", "Calibri.ttf"],
            "tahoma": ["tahoma.ttf", "Tahoma.ttf"],
            "verdana": ["verdana.ttf", "Verdana.ttf"],
            "times": ["times.ttf", "Times.ttf", "TimesNewRoman.ttf"],
            "courier": ["courier.ttf", "Courier.ttf", "CourierNew.ttf"]
        }
        
        for base_path in common_paths:
            if os.path.exists(base_path):
                for font_family, filenames in font_files.items():
                    for filename in filenames:
                        font_path = os.path.join(base_path, filename)
                        if os.path.exists(font_path):
                            font_paths.append(font_path)
                            break
        
        self.logger.info(f"Fontes descobertas: {len(font_paths)}")
        return font_paths
    
    def get_font(self, font_config: FontConfig) -> ImageFont.FreeTypeFont:
        """Obtém fonte com cache."""
        cache_key = f"{font_config.family}_{font_config.size}_{font_config.style}"
        
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]
        
        font = self._load_font(font_config)
        self._font_cache[cache_key] = font
        return font
    
    def _load_font(self, font_config: FontConfig) -> ImageFont.FreeTypeFont:
        """Carrega fonte do sistema."""
        try:
            # Tenta encontrar fonte específica
            for font_path in self._system_fonts:
                if font_config.family.lower() in os.path.basename(font_path).lower():
                    return ImageFont.truetype(font_path, font_config.size)
            
            # Fallback para primeira fonte disponível
            if self._system_fonts:
                return ImageFont.truetype(self._system_fonts[0], font_config.size)
            
            # Fallback final para fonte padrão
            self.logger.warning(f"Fonte {font_config.family} não encontrada, usando padrão")
            return ImageFont.load_default()
            
        except Exception as e:
            self.logger.error(f"Erro ao carregar fonte: {e}")
            return ImageFont.load_default()
    
    def clear_cache(self) -> None:
        """Limpa cache de fontes."""
        self._font_cache.clear()
        self.logger.info("Cache de fontes limpo")


class PositionCalculator:
    """Calculador de posições para marca d'água."""
    
    @staticmethod
    def calculate_position(
        image_size: Tuple[int, int],
        watermark_size: Tuple[int, int],
        position: WatermarkPosition,
        margin: int = 20
    ) -> Tuple[int, int]:
        """Calcula posição da marca d'água."""
        img_width, img_height = image_size
        wm_width, wm_height = watermark_size
        
        positions = {
            WatermarkPosition.TOP_LEFT: (margin, margin),
            WatermarkPosition.TOP_RIGHT: (img_width - wm_width - margin, margin),
            WatermarkPosition.TOP_CENTER: ((img_width - wm_width) // 2, margin),
            WatermarkPosition.BOTTOM_LEFT: (margin, img_height - wm_height - margin),
            WatermarkPosition.BOTTOM_RIGHT: (img_width - wm_width - margin, img_height - wm_height - margin),
            WatermarkPosition.BOTTOM_CENTER: ((img_width - wm_width) // 2, img_height - wm_height - margin),
            WatermarkPosition.CENTER: ((img_width - wm_width) // 2, (img_height - wm_height) // 2),
            WatermarkPosition.CENTER_LEFT: (margin, (img_height - wm_height) // 2),
            WatermarkPosition.CENTER_RIGHT: (img_width - wm_width - margin, (img_height - wm_height) // 2)
        }
        
        return positions.get(position, positions[WatermarkPosition.BOTTOM_RIGHT])
    
    @staticmethod
    def calculate_tile_positions(
        image_size: Tuple[int, int],
        watermark_size: Tuple[int, int],
        spacing: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        """Calcula posições para modo tile."""
        img_width, img_height = image_size
        wm_width, wm_height = watermark_size
        spacing_x, spacing_y = spacing
        
        positions = []
        
        y = 0
        while y < img_height:
            x = 0
            while x < img_width:
                if x + wm_width <= img_width and y + wm_height <= img_height:
                    positions.append((x, y))
                x += wm_width + spacing_x
            y += wm_height + spacing_y
        
        return positions


class BaseWatermarkProcessor(ABC):
    """Classe base para processadores de marca d'água."""
    
    def __init__(self, font_manager: FontManager):
        self.font_manager = font_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    def create_watermark_layer(
        self,
        image_size: Tuple[int, int],
        config: WatermarkConfig
    ) -> Image.Image:
        """Cria camada de marca d'água."""
        pass
    
    def apply_effects(self, layer: Image.Image, config: WatermarkConfig) -> Image.Image:
        """Aplica efeitos à camada de marca d'água."""
        if config.rotation != 0:
            layer = layer.rotate(config.rotation, expand=True)
        
        if config.blur_radius > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(radius=config.blur_radius))
        
        return layer


class TextWatermarkProcessor(BaseWatermarkProcessor):
    """Processador de marca d'água de texto."""
    
    def create_watermark_layer(
        self,
        image_size: Tuple[int, int],
        config: WatermarkConfig
    ) -> Image.Image:
        """Cria camada de marca d'água de texto."""
        # Cria camada transparente
        layer = Image.new('RGBA', image_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        
        # Obtém fonte
        font = self.font_manager.get_font(config.font_config)
        
        # Calcula tamanho do texto
        bbox = draw.textbbox((0, 0), config.text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        if config.tile_mode:
            # Modo tile
            positions = PositionCalculator.calculate_tile_positions(
                image_size, (text_width, text_height), config.tile_spacing
            )
        else:
            # Posição única
            positions = [PositionCalculator.calculate_position(
                image_size, (text_width, text_height), config.position, config.margin
            )]
        
        # Desenha texto em todas as posições
        for x, y in positions:
            # Sombra
            if config.font_config.shadow_offset != (0, 0):
                shadow_x = x + config.font_config.shadow_offset[0]
                shadow_y = y + config.font_config.shadow_offset[1]
                draw.text(
                    (shadow_x, shadow_y),
                    config.text,
                    font=font,
                    fill=config.font_config.shadow_color
                )
            
            # Contorno
            if config.font_config.outline_width > 0:
                for dx in range(-config.font_config.outline_width, config.font_config.outline_width + 1):
                    for dy in range(-config.font_config.outline_width, config.font_config.outline_width + 1):
                        if dx != 0 or dy != 0:
                            draw.text(
                                (x + dx, y + dy),
                                config.text,
                                font=font,
                                fill=config.font_config.outline_color
                            )
            
            # Texto principal
            draw.text((x, y), config.text, font=font, fill=config.font_config.color)
        
        return self.apply_effects(layer, config)


class LogoWatermarkProcessor(BaseWatermarkProcessor):
    """Processador de marca d'água de logo."""
    
    def create_watermark_layer(
        self,
        image_size: Tuple[int, int],
        config: WatermarkConfig
    ) -> Image.Image:
        """Cria camada de marca d'água de logo."""
        if not config.logo_path or not os.path.exists(config.logo_path):
            raise ValueError(f"Logo não encontrado: {config.logo_path}")
        
        # Cria camada transparente
        layer = Image.new('RGBA', image_size, (0, 0, 0, 0))
        
        # Carrega e processa logo
        with Image.open(config.logo_path) as logo:
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')
            
            # Redimensiona logo
            img_width, img_height = image_size
            logo_width = int(img_width * config.logo_scale)
            logo_height = int(logo.size[1] * (logo_width / logo.size[0]))
            logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
            
            # Aplica opacidade
            if config.logo_opacity < 1.0:
                alpha = logo.split()[-1]
                alpha = ImageEnhance.Brightness(alpha).enhance(config.logo_opacity)
                logo.putalpha(alpha)
            
            if config.tile_mode:
                # Modo tile
                positions = PositionCalculator.calculate_tile_positions(
                    image_size, (logo_width, logo_height), config.tile_spacing
                )
            else:
                # Posição única
                positions = [PositionCalculator.calculate_position(
                    image_size, (logo_width, logo_height), config.position, config.margin
                )]
            
            # Cola logo em todas as posições
            for x, y in positions:
                layer.paste(logo, (x, y), logo)
        
        return self.apply_effects(layer, config)


class WatermarkProcessor:
    """Processador principal de marca d'água com melhor performance."""
    
    def __init__(self, max_workers: int = 4):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.font_manager = FontManager()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        
        # Processadores especializados
        self.text_processor = TextWatermarkProcessor(self.font_manager)
        self.logo_processor = LogoWatermarkProcessor(self.font_manager)
        
        # Configurações padrão
        self.default_config = WatermarkConfig()
    
    async def process_image(
        self,
        image_path: str,
        config: Optional[WatermarkConfig] = None,
        output_path: Optional[str] = None
    ) -> str:
        """Processa imagem com marca d'água de forma assíncrona."""
        config = config or self.default_config
        
        # Valida entrada
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
        
        # Executa processamento em thread separada
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._process_image_sync,
            image_path,
            config,
            output_path
        )
    
    def _process_image_sync(
        self,
        image_path: str,
        config: WatermarkConfig,
        output_path: Optional[str]
    ) -> str:
        """Processamento síncrono da imagem."""
        try:
            with Image.open(image_path) as img:
                # Converte para RGBA para processamento
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Cria camada de marca d'água
                if config.type == WatermarkType.TEXT:
                    watermark_layer = self.text_processor.create_watermark_layer(img.size, config)
                elif config.type == WatermarkType.LOGO:
                    watermark_layer = self.logo_processor.create_watermark_layer(img.size, config)
                elif config.type == WatermarkType.COMBINED:
                    # Combina texto e logo
                    text_layer = self.text_processor.create_watermark_layer(img.size, config)
                    logo_layer = self.logo_processor.create_watermark_layer(img.size, config)
                    watermark_layer = Image.alpha_composite(text_layer, logo_layer)
                else:
                    raise ValueError(f"Tipo de marca d'água não suportado: {config.type}")
                
                # Aplica opacidade global
                if config.opacity < 1.0:
                    alpha = watermark_layer.split()[-1]
                    alpha = ImageEnhance.Brightness(alpha).enhance(config.opacity)
                    watermark_layer.putalpha(alpha)
                
                # Combina imagem com marca d'água
                result = Image.alpha_composite(img, watermark_layer)
                
                # Converte para formato de saída
                if not config.preserve_transparency or config.output_format.upper() == 'JPEG':
                    # Cria fundo branco para JPEG
                    background = Image.new('RGB', result.size, (255, 255, 255))
                    background.paste(result, mask=result.split()[-1])
                    result = background
                
                # Define caminho de saída
                if not output_path:
                    name, ext = os.path.splitext(image_path)
                    output_path = f"{name}_watermarked{ext}"
                
                # Salva imagem
                save_kwargs = {
                    'quality': config.output_quality,
                    'optimize': True
                }
                
                if config.output_format.upper() == 'PNG':
                    save_kwargs['compress_level'] = 6
                
                result.save(output_path, format=config.output_format, **save_kwargs)
                
                self.logger.info(f"Marca d'água aplicada: {output_path}")
                return output_path
                
        except Exception as e:
            self.logger.error(f"Erro ao processar imagem: {e}")
            raise
    
    async def process_batch(
        self,
        image_paths: List[str],
        config: Optional[WatermarkConfig] = None
    ) -> List[str]:
        """Processa múltiplas imagens em lote."""
        tasks = []
        for image_path in image_paths:
            task = self.process_image(image_path, config)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtra resultados válidos
        output_paths = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Erro ao processar {image_paths[i]}: {result}")
            else:
                output_paths.append(result)
        
        return output_paths
    
    async def process_watermark_request(
        self,
        context,
        chat_id: int,
        image_path: str,
        watermark_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Processa solicitação de marca d'água com feedback."""
        try:
            await send_progress_message(
                context, chat_id,
                "🎨 Aplicando marca d'água...",
                'processing', 25
            )
            
            # Converte configuração
            config = self._dict_to_config(watermark_config or {})
            
            # Processa imagem
            output_path = await self.process_image(image_path, config)
            
            await send_progress_message(
                context, chat_id,
                "📤 Enviando imagem com marca d'água...",
                'uploading', 75
            )
            
            # Envia imagem processada
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
                self.logger.warning(f"Erro ao remover arquivos temporários: {e}")
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Erro no processamento de marca d'água: {e}")
            await send_progress_message(
                context, chat_id,
                f"❌ Erro ao aplicar marca d'água: {str(e)[:100]}...",
                'error'
            )
            raise
    
    def _dict_to_config(self, config_dict: Dict[str, Any]) -> WatermarkConfig:
        """Converte dicionário para WatermarkConfig."""
        config = WatermarkConfig()
        
        # Configurações básicas
        if 'type' in config_dict:
            config.type = WatermarkType(config_dict['type'])
        if 'text' in config_dict:
            config.text = config_dict['text']
        if 'position' in config_dict:
            if isinstance(config_dict['position'], str):
                config.position = WatermarkPosition(config_dict['position'])
        if 'opacity' in config_dict:
            config.opacity = float(config_dict['opacity'])
        
        # Configurações de fonte
        if 'font_size' in config_dict:
            config.font_config.size = int(config_dict['font_size'])
        
        # Configurações de logo
        if 'logo_path' in config_dict:
            config.logo_path = config_dict['logo_path']
        if 'scale' in config_dict:
            config.logo_scale = float(config_dict['scale'])
        
        return config
    
    def clear_caches(self) -> None:
        """Limpa todos os caches."""
        self.font_manager.clear_cache()
        self.logger.info("Caches limpos")
    
    def shutdown(self) -> None:
        """Finaliza o processador."""
        self.executor.shutdown(wait=True)
        self.logger.info("WatermarkProcessor finalizado")


# Instância global para compatibilidade
_watermark_processor = WatermarkProcessor()

# Funções de compatibilidade
async def apply_text_watermark(
    context,
    chat_id: int,
    image_path: str,
    text: Optional[str] = None,
    position: str = "bottom_right",
    opacity: float = 0.7
) -> str:
    """Função de compatibilidade para marca d'água de texto."""
    config = {
        'type': 'text',
        'text': text,
        'position': position,
        'opacity': opacity
    }
    return await _watermark_processor.process_watermark_request(
        context, chat_id, image_path, config
    )


async def apply_logo_watermark(
    context,
    chat_id: int,
    image_path: str,
    logo_path: str,
    position: str = "bottom_right",
    opacity: float = 0.7,
    scale: float = 0.1
) -> str:
    """Função de compatibilidade para marca d'água de logo."""
    config = {
        'type': 'logo',
        'logo_path': logo_path,
        'position': position,
        'opacity': opacity,
        'scale': scale
    }
    return await _watermark_processor.process_watermark_request(
        context, chat_id, image_path, config
    )


# Instância global para compatibilidade
watermark_processor = _watermark_processor