/**
 * 发音：有道真人音频优先，失败回落浏览器 TTS（speechSynthesis）。
 *
 * - accent: 'uk' / 'us'，由调用方按用户点击的音标块（或发音偏好）传入
 * - 返回 Promise：resolve('youdao') 真人音频播完；resolve('tts') 已回落 TTS 播完；
 *   reject(Error) 两者都不可用（如无声音设备 + 浏览器不支持 TTS）
 * - 重复调用会先停掉上一段，避免叠音
 */

let currentAudio = null

function stopCurrent() {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.src = ''
    currentAudio = null
  }
  if (window.speechSynthesis) window.speechSynthesis.cancel()
}

function playYoudao(word, accent) {
  return new Promise((resolve, reject) => {
    const type = accent === 'uk' ? 1 : 2
    const url = `https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=${type}`
    const audio = new Audio(url)
    currentAudio = audio
    const fail = () => {
      if (currentAudio === audio) currentAudio = null
      reject(new Error('audio unavailable'))
    }
    audio.onerror = fail
    audio.onended = () => {
      if (currentAudio === audio) currentAudio = null
      resolve('youdao')
    }
    audio.play().catch(fail)
  })
}

function pickVoice(lang) {
  const voices = window.speechSynthesis?.getVoices() || []
  return (
    voices.find((v) => v.lang === lang) ||
    voices.find((v) => v.lang.startsWith(lang.split('-')[0])) ||
    null
  )
}

function playTts(word, accent) {
  return new Promise((resolve, reject) => {
    if (!window.speechSynthesis) {
      reject(new Error('当前浏览器不支持语音合成'))
      return
    }
    const utt = new SpeechSynthesisUtterance(word)
    utt.lang = accent === 'uk' ? 'en-GB' : 'en-US'
    const voice = pickVoice(utt.lang)
    if (voice) utt.voice = voice
    utt.rate = 0.9
    utt.onend = () => resolve('tts')
    utt.onerror = (e) => reject(new Error(e.error || '语音合成失败'))
    window.speechSynthesis.speak(utt)
  })
}

export async function speak(word, accent = 'us') {
  const text = (word || '').trim()
  if (!text) throw new Error('没有可朗读的内容')
  stopCurrent()
  try {
    return await playYoudao(text, accent)
  } catch {
    return await playTts(text, accent)
  }
}

export function stopSpeaking() {
  stopCurrent()
}
