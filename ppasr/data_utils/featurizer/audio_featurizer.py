import numpy as np
import paddle
from paddleaudio.compliance.kaldi import mfcc, fbank

from ppasr.data_utils.audio import AudioSegment


class AudioFeaturizer(object):
    """音频特征器

    :param target_sample_rate: 用于训练的音频的采样率
    :type target_sample_rate: int
    :param use_dB_normalization: 是否对音频进行音量归一化
    :type use_dB_normalization: bool
    :param target_dB: 对音频进行音量归一化的音量分贝值
    :type target_dB: float
    :param allow_downsampling: 是否允许对音频采样率进行下采样
    :type allow_downsampling: bool
    :param allow_upsampling: 是否允许对音频采样率进行上采样
    :type allow_upsampling: bool
    """

    def __init__(self,
                 feature_method='linear',
                 target_sample_rate=16000,
                 use_dB_normalization=True,
                 target_dB=-20,
                 allow_downsampling=True,
                 allow_upsampling=True,
                 train=False):
        self._feature_method = feature_method
        self._target_sample_rate = target_sample_rate
        self._use_dB_normalization = use_dB_normalization
        self._target_dB = target_dB
        self._allow_downsampling = allow_downsampling
        self._allow_upsampling = allow_upsampling
        self.train = train

    def featurize(self, audio_segment):
        """从AudioSegment中提取音频特征

        :param audio_segment: Audio segment to extract features from.
        :type audio_segment: AudioSegment
        :return: Spectrogram audio feature in 2darray.
        :rtype: ndarray
        """
        # upsampling or downsampling
        if ((audio_segment.sample_rate > self._target_sample_rate and self._allow_downsampling) or
                (audio_segment.sample_rate < self._target_sample_rate and self._allow_upsampling)):
            audio_segment.resample(self._target_sample_rate)
        if audio_segment.sample_rate != self._target_sample_rate:
            raise ValueError("Audio sample rate is not supported. "
                             "Turn allow_downsampling or allow up_sampling on.")
        # decibel normalization
        if self._use_dB_normalization:
            audio_segment.normalize(target_db=self._target_dB)
        # extract spectrogram
        if self._feature_method == 'linear':
            samples = audio_segment.samples
            return self._compute_linear(samples=samples, sample_rate=audio_segment.sample_rate)
        elif self._feature_method == 'mfcc':
            samples = audio_segment.to('int16')
            return self._compute_mfcc(samples=samples, sample_rate=audio_segment.sample_rate)
        elif self._feature_method == 'fbank':
            samples = audio_segment.to('int16')
            return self._compute_fbank(samples=samples, sample_rate=audio_segment.sample_rate)
        else:
            raise Exception('没有{}预处理方法'.format(self._feature_method))

    # 线性谱图
    @staticmethod
    def _compute_linear(samples, sample_rate, frame_shift=10.0, frame_length=20.0, eps=1e-14):
        stride_size = int(0.001 * sample_rate * frame_shift)
        window_size = int(0.001 * sample_rate * frame_length)
        truncate_size = (len(samples) - window_size) % stride_size
        samples = samples[:len(samples) - truncate_size]
        nshape = (window_size, (len(samples) - window_size) // stride_size + 1)
        nstrides = (samples.strides[0], samples.strides[0] * stride_size)
        windows = np.lib.stride_tricks.as_strided(samples, shape=nshape, strides=nstrides)
        assert np.all(windows[:, 1] == samples[stride_size:(stride_size + window_size)])
        # 快速傅里叶变换
        weighting = np.hanning(window_size)[:, None]
        fft = np.fft.rfft(windows * weighting, n=None, axis=0)
        fft = np.absolute(fft)
        fft = fft ** 2
        scale = np.sum(weighting ** 2) * sample_rate
        fft[1:-1, :] *= (2.0 / scale)
        fft[(0, -1), :] /= scale
        freqs = float(sample_rate) / window_size * np.arange(fft.shape[0])
        ind = np.where(freqs <= (sample_rate / 2))[0][-1] + 1
        linear_feat = np.log(fft[:ind, :] + eps)
        linear_feat = linear_feat.transpose([1, 0])  # (T, 161)
        return linear_feat

    # Mel频率倒谱系数(MFCC)
    def _compute_mfcc(self,
                      samples,
                      sample_rate,
                      n_mels=80,
                      n_mfcc=40,
                      frame_shift=10,
                      frame_length=25,
                      dither=0.1):
        dither = dither if self.train else 0.0
        waveform = paddle.to_tensor(np.expand_dims(samples, 0), dtype=paddle.float32)
        # 计算MFCC
        mfcc_feat = mfcc(waveform,
                         n_mels=n_mels,
                         n_mfcc=n_mfcc,
                         frame_length=frame_length,
                         frame_shift=frame_shift,
                         dither=dither,
                         sr=sample_rate)
        mfcc_feat = mfcc_feat.numpy()  # (T, 40)
        return mfcc_feat

    # Fbank
    def _compute_fbank(self,
                       samples,
                       sample_rate,
                       n_mels=161,
                       frame_shift=10,
                       frame_length=25,
                       dither=0.1):
        dither = dither if self.train else 0.0
        waveform = paddle.to_tensor(np.expand_dims(samples, 0), dtype=paddle.float32)
        # 计算Fbank
        mat = fbank(waveform,
                    n_mels=n_mels,
                    frame_length=frame_length,
                    frame_shift=frame_shift,
                    dither=dither,
                    sr=sample_rate)
        fbank_feat = mat.numpy()  # (T, 161)
        return fbank_feat

    @property
    def feature_dim(self):
        """返回特征大小

        :return: 特征大小
        :rtype: int
        """
        if self._feature_method == 'linear':
            return 161
        elif self._feature_method == 'mfcc':
            return 40
        elif self._feature_method == 'fbank':
            return 161
        else:
            raise Exception('没有{}预处理方法'.format(self._feature_method))
