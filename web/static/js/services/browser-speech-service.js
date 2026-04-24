export class BrowserSpeechService {
  constructor(options = {}) {
    this.isEnabled = typeof options.isEnabled === "function"
      ? options.isEnabled
      : () => true;
    this.cachedVoice = null;
    this.refreshSelectedVoice = this.refreshSelectedVoice.bind(this);

    if (window.speechSynthesis) {
      this.refreshSelectedVoice();
      if (typeof window.speechSynthesis.addEventListener === "function") {
        window.speechSynthesis.addEventListener("voiceschanged", this.refreshSelectedVoice);
      }
    }
  }

  refreshSelectedVoice() {
    this.cachedVoice = this.pickVietnameseVoice();
    return this.cachedVoice;
  }

  pickVietnameseVoice() {
    if (!window.speechSynthesis) {
      return null;
    }

    const voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length) {
      return null;
    }

    const scored = voices.map((voice) => {
      const name = String(voice.name || "").toLowerCase();
      const lang = String(voice.lang || "").toLowerCase();
      const voiceId = String(voice.voiceURI || voice.id || "").toLowerCase();
      let score = 0;

      if (lang === "vi-vn") {
        score += 160;
      } else if (lang.startsWith("vi")) {
        score += 120;
      }
      if (name.includes("google")) {
        score += 30;
      }
      if (name.includes("microsoft an") || voiceId.includes("microsoft an")) {
        score += 80;
      }
      if (
        name.includes("vietnam")
        || name.includes("viet")
        || name.includes("tiếng việt")
        || name.includes("tieng viet")
        || voiceId.includes("vi-vn")
      ) {
        score += 30;
      }
      if (name.includes("female") || name.includes("nu")) {
        score += 10;
      }
      if (voice.localService) {
        score += 10;
      }
      if (voice.default) {
        score += 5;
      }

      return { voice, score };
    });

    scored.sort((a, b) => b.score - a.score);
    return scored[0] && scored[0].score > 0 ? scored[0].voice : null;
  }

  speak(messages, clearQueue = false, onEndCallback = null) {
    if (clearQueue && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (!this.isEnabled() || !window.speechSynthesis || !Array.isArray(messages) || messages.length === 0) {
      if (typeof onEndCallback === "function") {
        setTimeout(onEndCallback, 4500); // Emulate countdown time
      }
      return;
    }

    const validMessages = messages.filter(m => m && String(m).trim());
    if (validMessages.length === 0) {
      if (typeof onEndCallback === "function") {
        setTimeout(onEndCallback, 4500);
      }
      return;
    }

    validMessages.forEach((message, index) => {
      const utterance = new SpeechSynthesisUtterance(String(message));
      utterance.lang = "vi-VN";
      const voice = this.cachedVoice || this.refreshSelectedVoice();
      if (voice) {
        utterance.voice = voice;
      }
      utterance.rate = 1.0;
      
      window._speechUtterances = window._speechUtterances || [];
      window._speechUtterances.push(utterance);

      let callbackFired = false;
      const safeCallback = () => {
        // Remove from GC protection array
        const uIdx = window._speechUtterances.indexOf(utterance);
        if (uIdx > -1) window._speechUtterances.splice(uIdx, 1);

        if (!callbackFired && typeof onEndCallback === "function") {
          callbackFired = true;
          onEndCallback();
        }
      };

      if (index === validMessages.length - 1) {
        if (typeof onEndCallback === "function") {
          utterance.onend = safeCallback;
          utterance.onerror = safeCallback;
          // Fallback: in case Chrome's onend bug occurs, fire it after an estimated time
          let estimatedMs = validMessages.length * 1000 + 1000;
          const fullText = validMessages.join(" ");
          if (fullText.includes("Sẵn sàng") && fullText.includes("Bắt đầu")) {
            estimatedMs = Math.max(estimatedMs, 5000);
          }
          setTimeout(safeCallback, estimatedMs);
        } else {
          utterance.onend = () => {
            const uIdx = window._speechUtterances.indexOf(utterance);
            if (uIdx > -1) window._speechUtterances.splice(uIdx, 1);
          };
        }
      } else {
        utterance.onend = () => {
          const uIdx = window._speechUtterances.indexOf(utterance);
          if (uIdx > -1) window._speechUtterances.splice(uIdx, 1);
        };
      }
      
      window.speechSynthesis.speak(utterance);
    });
  }
}
