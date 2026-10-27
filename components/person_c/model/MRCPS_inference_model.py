import torch
from torch import nn
import torch.nn.functional as F
import numpy as np
from typing import Optional, List

from .model_segformer import SegformerEncoder
from .model_resnest import resnest26d


class SegformerConfig():
    
    model_type = "segformer"

    def __init__(
        self,
        num_channels=3,
        num_encoder_blocks=4,
        depths=[2, 2, 2, 2],
        sr_ratios=[8, 4, 2, 1],
        hidden_sizes=[64, 128, 320, 512],
        patch_sizes=[7, 3, 3, 3],
        strides=[4, 2, 2, 2],
        num_attention_heads=[1, 2, 5, 8],
        mlp_ratios=[4, 4, 4, 4],
        hidden_act="gelu",
        hidden_dropout_prob=0.0,
        attention_probs_dropout_prob=0.0,
        classifier_dropout_prob=0.1,
        initializer_range=0.02,
        drop_path_rate=0.1,
        layer_norm_eps=1e-6,
        decoder_hidden_size=256,
        semantic_loss_ignore_index=255,
        image_size=512,
        multi_scale = 2,
        num_class = 2,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.num_channels = num_channels
        self.num_encoder_blocks = num_encoder_blocks
        self.depths = depths
        self.sr_ratios = sr_ratios
        self.hidden_sizes = hidden_sizes
        self.patch_sizes = patch_sizes
        self.strides = strides
        self.mlp_ratios = mlp_ratios
        self.num_attention_heads = num_attention_heads
        self.hidden_act = hidden_act
        self.hidden_dropout_prob = hidden_dropout_prob
        self.attention_probs_dropout_prob = attention_probs_dropout_prob
        self.classifier_dropout_prob = classifier_dropout_prob
        self.initializer_range = initializer_range
        self.drop_path_rate = drop_path_rate
        self.layer_norm_eps = layer_norm_eps
        self.decoder_hidden_size = decoder_hidden_size
        self.reshape_last_stage = kwargs.get("reshape_last_stage", True)
        self.semantic_loss_ignore_index = semantic_loss_ignore_index
        self.image_size = image_size
        self.multi_scale = multi_scale
        self.num_class = num_class

class Conv2dBnAct(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, padding=0,
                 stride=1, act_layer=nn.ReLU, norm_layer=nn.BatchNorm2d):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride=stride, padding=padding, bias=False)
        self.bn = norm_layer(out_channels) if norm_layer is not None else nn.Identity()

        self.act = act_layer() if act_layer == nn.GELU else \
            act_layer(inplace=True) if act_layer is not None else nn.Identity()

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.act(x)
        return x
        
class SegformerMLP(nn.Module):
    """
    Linear Embedding.
    """

    def __init__(self, input_dim, decoder_hidden_size=256):
        super().__init__()
        self.proj = nn.Linear(input_dim, decoder_hidden_size)

    def forward(self, hidden_states: torch.Tensor):
        hidden_states = hidden_states.flatten(2).transpose(1, 2)
        hidden_states = self.proj(hidden_states)
        return hidden_states

class MScenterMLP(nn.Module):
    def __init__(self, hidden_sizes, decoder_hidden_size, lrscale):
        super().__init__()
        self.linear_c = nn.ModuleList()
        for input_dim in hidden_sizes:
            mlp = SegformerMLP(input_dim=input_dim, decoder_hidden_size=decoder_hidden_size)
            self.linear_c.append(mlp)
        
        self.lrscale = lrscale

    def forward(self, lr: torch.Tensor):
        B, _, H, W = lr[-1].size()

        hidden_states = ()
        for centerlr, mlp in zip(lr, self.linear_c):
            ylen, xlen = centerlr.shape[-2:]
            centerlr = mlp(centerlr)
            centerlr = centerlr.permute(0, 2, 1)
            centerlr = centerlr.reshape(B, -1, ylen, xlen)

            centerlr = centerlr[..., ylen//2-ylen//2//self.lrscale-1:ylen//2+ylen//2//self.lrscale+1, \
                        xlen//2-xlen//2//self.lrscale-1:xlen//2+xlen//2//self.lrscale+1]
            centerlr = F.interpolate(centerlr, scale_factor=self.lrscale, mode="bilinear", align_corners=False)
            centerlr = centerlr[..., self.lrscale:centerlr.shape[-2]-self.lrscale,\
                                self.lrscale:centerlr.shape[-1]-self.lrscale]
            centerlr = F.interpolate(
                    centerlr, size=(H, W), mode='area')
            hidden_states += (centerlr,)

        return torch.cat(hidden_states, dim=1)

class DecoderBlock(nn.Module):
    def __init__(self, in_channels, out_channels, scale_factor=2.0, act_layer=nn.ReLU, norm_layer=nn.BatchNorm2d):
        super().__init__()
        conv_args = dict(kernel_size=3, padding=1, norm_layer=norm_layer, act_layer=act_layer)
        self.scale_factor = scale_factor
        self.conv1 = Conv2dBnAct(in_channels, out_channels, **conv_args)
        self.conv2 = Conv2dBnAct(out_channels, out_channels, **conv_args)

    def forward(self, x, skip: Optional[torch.Tensor] = None):
        if self.scale_factor != 1.0:
            x = F.interpolate(x, scale_factor=self.scale_factor, mode='bilinear')
        if skip is not None:
            x = torch.cat([x, skip], dim=1)
        x = self.conv1(x)
        x = self.conv2(x)
        return x

class UnetDecoder(nn.Module):

    def __init__(
            self,
            encoder_channels,
            decoder_channels=(256, 128, 64, 32, 16),
            final_channels=2,
            act_layer=nn.ReLU,
            norm_layer=nn.BatchNorm2d,
            block=DecoderBlock,
            center=False,
    ):
        super().__init__()

        conv_args = dict(norm_layer=norm_layer, act_layer=act_layer)
        if center:
            channels = encoder_channels[0]
            self.center = block(channels, channels, scale_factor=1.0, **conv_args)
        else:
            self.center = nn.Identity()

        in_channels = [in_chs + skip_chs for in_chs, skip_chs in zip(
            [encoder_channels[0]] + list(decoder_channels[:-1]),
            list(encoder_channels[1:]) + [0])]
        out_channels = decoder_channels

        self.blocks = nn.ModuleList()
        for in_chs, out_chs in zip(in_channels, out_channels):
            if out_chs == decoder_channels[-1]:
                self.blocks.append(DecoderBlock(in_chs, out_chs, **conv_args))
            else:
                self.blocks.append(block(in_chs, out_chs, **conv_args))

        self.final_conv = nn.Conv2d(out_channels[-1], final_channels, kernel_size=(3, 3), stride=(1, 1), padding=(1, 1))

        #initialize_decoder(self.blocks)
        #initialize_head(self.final_conv)

    def forward(self, x: List[torch.Tensor]):
        encoder_head = x[0]
        skips = x[1:]
        x = self.center(encoder_head)
        for i, b in enumerate(self.blocks):
            skip = skips[i] if i < len(skips) else None
            x = b(x, skip)
        x = self.final_conv(x)
        return x
    
    
    
class MRCPS(nn.Module):
    def __init__(self):
        super().__init__()
        
        encoder_name = 'resnest26d'
        lrencoder_name = 'nvidia/mit-b1'
        decoder_channels=(256, 128, 64, 32, 16)
        lrscale=8
        classes=2
        
        backbone_kwargs = {}
        self.encoder = resnest26d(features_only=True, out_indices=None, in_chans=3,pretrained=False, **backbone_kwargs)
        encoder_channels = [ info['num_chs'] for info in self.encoder.feature_info ]
        
        config = SegformerConfig()
        self.lrencoder = SegformerEncoder(config)
        lrencoder_channels = config.hidden_sizes
        
        self.mscenter_mlp = MScenterMLP(lrencoder_channels, decoder_hidden_size=256, lrscale=lrscale)
        
        if encoder_channels[-1] > 1024:
            self.fusionblock = Conv2dBnAct(
                1024 + encoder_channels[-1], encoder_channels[-1] // 2, kernel_size=(1, 1))
            encoder_channels[-1] //= 2
        else:
            self.fusionblock = Conv2dBnAct(
                1024 + encoder_channels[-1], encoder_channels[-1], kernel_size=(1, 1))

        #initialize_decoder(self.fusionblock)

        self.lrscale = lrscale

        self.decoder = UnetDecoder(
            encoder_channels=encoder_channels[::-1],
            decoder_channels=decoder_channels[:len(encoder_channels)],
            final_channels=classes,
        )

    def forward(self, x, lr, need_fp=False):
        _, _, h, w = x.shape

        x = self.encoder(x)
        x.reverse()

        lr, _ = self.lrencoder(lr)[-4:]
        centerlr = self.mscenter_mlp(lr)

        x[0] = self.fusionblock(torch.concat((x[0], centerlr), dim=1))

        if need_fp:
            for i in range(len(x)):
                x[i] = nn.Dropout2d(0.5)(x[i])

            out_fp = self.decoder(x)
            out_fp = F.interpolate(out_fp, size=(h, w), mode="bilinear", align_corners=False)

            return out_fp

        predmask = self.decoder(x)
        predmask = F.interpolate(predmask, size=(h,w), mode="bilinear", align_corners=False)

        return torch.argmax(predmask, dim=1)
    
    
