''' Define the Transformer model '''
import torch
import torch.nn as nn
import numpy as np
from transformer.Layers import EncoderLayer, DecoderLayer


__author__ = "Yu-Hsiang Huang"
#pad_mask原理：
#在RNN中序列可以不定长，可是在transformer中是需要定长的，
#这意味着需要设置一个最大长度，小于最大长度的全部补0，这些补0的就被称为<PAD>

# 获取mask并增加一个维度
# (batch_size, seq_len) => (batch_size, 1, seq_len) ：(1, 3) => (1, 1, 3)

########### 如输入seq为[[1,2,0]] 输出为 [[[1 1 0]]]#############
def get_pad_mask(seq, pad_idx):
    # pad_idx一般为0
    return (seq != pad_idx).unsqueeze(-2)
#padding mask：处理非定长序列，区分padding和非padding部分。
#对应下面get_pad_mask()函数，用于Encoder中。


#在decoder使用mask为get_pad_mask()得到的结果和get_subsequent_mask()得到的结果进行与运算
def get_subsequent_mask(seq):
    #sequence mask：防止标签泄露。
    # sequence mask 一般是通过生成一个上三角为0的矩阵来实现的，上三角区域对应要mask的部分。
    ''' For masking out the subsequent info. '''
    sz_b, len_s = seq.size()
    # 例如输入的seq的shape为(1, 3)，torch.triu(torch.ones((1, len_s, len_s), device=seq.device), diagonal=1))的结果是:
    # [[[0 1 1]
    #   [0 0 1]
    #   [0 0 0]]]

    #                   [[[1 0 0]
    # subsequent_mask =   [1 1 0]
    #                     [1 1 1]]]

    # get_pad_mask()得到的结果和get_subsequent_mask()得到的结果进行与运算（&）
    #               [[[1 0 0]      [[[1 0 0]
    # [[[1 1 0]]] &   [1 1 0]   =    [1 1 0]
    #                 [1 1 1]]]      [1 1 0]]]
    # 我认为是既要区分padding和非padding部分，也要防止标签泄露。
    subsequent_mask = (1 - torch.triu(
        torch.ones((1, len_s, len_s), device=seq.device), diagonal=1)).bool()
    return subsequent_mask

class PositionalEncoding(nn.Module):

    def __init__(self, d_hid, n_position=200):
        super(PositionalEncoding, self).__init__()

        # Not a parameter
        self.register_buffer('pos_table', self._get_sinusoid_encoding_table(n_position, d_hid))

    def _get_sinusoid_encoding_table(self, n_position, d_hid):
        # n_position默认为200 d_hid默认为d512
        ''' Sinusoid position encoding table '''
        # TODO: make it with torch instead of numpy

        # 利用论文中的公式获取某个位置的向量
        def get_position_angle_vec(position):
            # 长度为512 (hid_j // 2)就是论文中的i
            return [position / np.power(10000, 2 * (hid_j // 2) / d_hid) for hid_j in range(d_hid)]
        # shape为(200, 512)
        sinusoid_table = np.array([get_position_angle_vec(pos_i) for pos_i in range(n_position)])
        # 偶数位置使用sin编码
        sinusoid_table[:, 0::2] = np.sin(sinusoid_table[:, 0::2])  # dim 2i
        # 奇数位置使用cos编码
        sinusoid_table[:, 1::2] = np.cos(sinusoid_table[:, 1::2])  # dim 2i+1
        # shape为(1, n_position, d_hid)
        return torch.FloatTensor(sinusoid_table).unsqueeze(0)

    def forward(self, x):
        # n_position默认为200 seq_len不会超过200
        # 这里x加入位置编码
        return x + self.pos_table[:, :x.size(1)].clone().detach()

class Encoder(nn.Module):
    ''' A encoder model with self attention mechanism. '''

    def __init__(
            self, n_src_vocab, d_word_vec, n_layers, n_head, d_k, d_v,
            d_model, d_inner, pad_idx, dropout=0.1, n_position=200, scale_emb=False):
        # n_src_vocab: 源语言词汇表的大小
        # d_word_vec: 词嵌入的维度
        super().__init__()

        # padding_idx如果指定 则padding_idx处的条目不会影响梯度
        # 因此padding_idx 处的嵌入向量在训练期间不会更新 即它仍然是一个固定的"pad"
        self.src_word_emb = nn.Embedding(n_src_vocab, d_word_vec, padding_idx=pad_idx)
        self.position_enc = PositionalEncoding(d_word_vec, n_position=n_position)
        self.dropout = nn.Dropout(p=dropout)
        # Encoder包含了n_layers个EncoderLayer（n_layers默认为6）
        self.layer_stack = nn.ModuleList([
            EncoderLayer(d_model, d_inner, n_head, d_k, d_v, dropout=dropout)
            for _ in range(n_layers)])
        self.layer_norm = nn.LayerNorm(d_model, eps=1e-6)
        self.scale_emb = scale_emb
        self.d_model = d_model

    def forward(self, src_seq, src_mask, return_attns=False):
        # src_seq: 输入的序列
        # src_mask: get_pad_mask()得到的结果
        enc_slf_attn_list = []

        # -- Forward
        # 词嵌入
        enc_output = self.src_word_emb(src_seq)
        if self.scale_emb:
            enc_output *= self.d_model ** 0.5
        # 加上位置编码
        enc_output = self.dropout(self.position_enc(enc_output))
        enc_output = self.layer_norm(enc_output)
        # n_layers个EncoderLayer串联在一起
        for enc_layer in self.layer_stack:
            enc_output, enc_slf_attn = enc_layer(enc_output, slf_attn_mask=src_mask)
            enc_slf_attn_list += [enc_slf_attn] if return_attns else []

        if return_attns:
            return enc_output, enc_slf_attn_list
        return enc_output,


class Decoder(nn.Module):
    ''' A decoder model with self attention mechanism. '''
    def __init__(
            self, n_trg_vocab, d_word_vec, n_layers, n_head, d_k, d_v,
            d_model, d_inner, pad_idx, n_position=200, dropout=0.1, scale_emb=False):
        # n_trg_vocab: 翻译后语言词汇表的大小
        # d_word_vec: 词嵌入的维度
        super().__init__()

        self.trg_word_emb = nn.Embedding(n_trg_vocab, d_word_vec, padding_idx=pad_idx)
        self.position_enc = PositionalEncoding(d_word_vec, n_position=n_position)
        self.dropout = nn.Dropout(p=dropout)
        # Decoder包含了n_layers个DecoderLayer n_layers默认为6
        self.layer_stack = nn.ModuleList([
            DecoderLayer(d_model, d_inner, n_head, d_k, d_v, dropout=dropout)
            for _ in range(n_layers)])
        self.layer_norm = nn.LayerNorm(d_model, eps=1e-6)
        self.scale_emb = scale_emb
        self.d_model = d_model

    def forward(self, trg_seq, trg_mask, enc_output, src_mask, return_attns=False):
        # trg_seq：翻译后语言序列
        # trg_mask: get_pad_mask()得到的结果和get_subsequent_mask()得到的结果进行与运算（&）
        # enc_output: Encoder的输出
        # src_mask: get_pad_mask()得到的结果
        dec_slf_attn_list, dec_enc_attn_list = [], []

        # -- Forward
        # 词嵌入
        dec_output = self.trg_word_emb(trg_seq)
        if self.scale_emb:
            dec_output *= self.d_model ** 0.5
        # 加上位置编码
        dec_output = self.dropout(self.position_enc(dec_output))
        dec_output = self.layer_norm(dec_output)
        # n_layers个DecoderLayer串联在一起
        for dec_layer in self.layer_stack:
            dec_output, dec_slf_attn, dec_enc_attn = dec_layer(
                dec_output, enc_output, slf_attn_mask=trg_mask, dec_enc_attn_mask=src_mask)
            dec_slf_attn_list += [dec_slf_attn] if return_attns else []
            dec_enc_attn_list += [dec_enc_attn] if return_attns else []
        #slf是带mask的 enc是不带mask的
        if return_attns:
            return dec_output, dec_slf_attn_list, dec_enc_attn_list
        return dec_output,


class Transformer(nn.Module):
    ''' A sequence to sequence model with attention mechanism. '''
    # n_src_vocab: 源语言词汇表的大小
    # n_trg_vocab: 翻译后词汇表的大小
    def __init__(
            self, n_src_vocab, n_trg_vocab, src_pad_idx, trg_pad_idx,
            d_word_vec=512, d_model=512, d_inner=2048,
            n_layers=6, n_head=8, d_k=64, d_v=64, dropout=0.1, n_position=200,
            trg_emb_prj_weight_sharing=True, emb_src_trg_weight_sharing=True,
            scale_emb_or_prj='prj'):

        super().__init__()

        self.src_pad_idx, self.trg_pad_idx = src_pad_idx, trg_pad_idx

        # In section 3.4 of paper "Attention Is All You Need", there is such detail:
        # "In our model, we share the same weight matrix between the two
        # embedding layers and the pre-softmax linear transformation...
        # In the embedding layers, we multiply those weights by \sqrt{d_model}".
        #
        # Options here:
        #   'emb': multiply \sqrt{d_model} to embedding output
        #   'prj': multiply (\sqrt{d_model} ^ -1) to linear projection output
        #   'none': no multiplication
        assert scale_emb_or_prj in ['emb', 'prj', 'none']
        scale_emb = (scale_emb_or_prj == 'emb') if trg_emb_prj_weight_sharing else False
        self.scale_prj = (scale_emb_or_prj == 'prj') if trg_emb_prj_weight_sharing else False
        self.d_model = d_model

        self.encoder = Encoder(
            n_src_vocab=n_src_vocab, n_position=n_position,
            d_word_vec=d_word_vec, d_model=d_model, d_inner=d_inner,
            n_layers=n_layers, n_head=n_head, d_k=d_k, d_v=d_v,
            pad_idx=src_pad_idx, dropout=dropout, scale_emb=scale_emb)

        self.decoder = Decoder(
            n_trg_vocab=n_trg_vocab, n_position=n_position,
            d_word_vec=d_word_vec, d_model=d_model, d_inner=d_inner,
            n_layers=n_layers, n_head=n_head, d_k=d_k, d_v=d_v,
            pad_idx=trg_pad_idx, dropout=dropout, scale_emb=scale_emb)

        self.trg_word_prj = nn.Linear(d_model, n_trg_vocab, bias=False)

        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p) 

        assert d_model == d_word_vec, \
        'To facilitate the residual connections, \
         the dimensions of all module outputs shall be the same.'

        # Decoder中Embedding层和FC层权重共享
        # Embedding层参数维度是：(v,d)，FC层参数维度是：(d,v)，可以直接共享嘛，还是要转置？其中v是词表大小，d是embedding维度。
        # 查看 pytorch 源码发现真的可以直接共享：
        if trg_emb_prj_weight_sharing:
            # Share the weight between target word embedding & last dense layer
            self.trg_word_prj.weight = self.decoder.trg_word_emb.weight
        # Encoder和Decoder间的Embedding层权重共享
        if emb_src_trg_weight_sharing:
            self.encoder.src_word_emb.weight = self.decoder.trg_word_emb.weight


    def forward(self, src_seq, trg_seq):

        src_mask = get_pad_mask(src_seq, self.src_pad_idx)
        trg_mask = get_pad_mask(trg_seq, self.trg_pad_idx) & get_subsequent_mask(trg_seq)

        enc_output, *_ = self.encoder(src_seq, src_mask)
        dec_output, *_ = self.decoder(trg_seq, trg_mask, enc_output, src_mask)
        seq_logit = self.trg_word_prj(dec_output)
        if self.scale_prj:
            seq_logit *= self.d_model ** -0.5

        return seq_logit.view(-1, seq_logit.size(2))
