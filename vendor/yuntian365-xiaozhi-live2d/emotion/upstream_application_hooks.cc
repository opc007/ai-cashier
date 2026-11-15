// Excerpt from yuntian365/xiaozhi-p4-dfrobot xiaozhi-esp32/main/application.cc
// (upstream firmware base 78/xiaozhi-esp32 v2.5.3). Not compiled into ai-cashier.
// ai-cashier is v2.5.2, where Display::SetEmotion returns void, so the call
// `if (display->SetEmotion(emotion))` does not build here. The adapted entry
// point is firmware_patches/main/character/character_emotion.h.
// Source: https://gitee.com/yuntian365/xiaozhi-p4-dfrobot
// Article: https://mc.dfrobot.com.cn/article-387130.html

// --- application.cc:30-44 ---
namespace {

// Live2D character pack: "idle" (breathing + blinking) and "speaking" (mouth
// movement) are looping GIFs registered from the assets partition. Boards that
// run the stock assets fall back to the neutral face, preserving upstream
// behaviour.
template <typename DisplayPtr>
void SetCharacterEmotion(DisplayPtr display, const char* emotion) {
    if (display->SetEmotion(emotion)) {
        ESP_LOGI(TAG, "Character emotion: %s", emotion);
    } else {
        display->SetEmotion("neutral");
    }
}


// --- application.cc:476-482 ---
    // Apply assets
    assets.Apply();
    display->SetChatMessage("system", "");
    // Live2D character pack: "idle" is a breathing + blinking GIF registered from
    // the assets partition. Boards without the custom pack keep the neutral face.
    SetCharacterEmotion(display, "idle");
}

// --- application.cc:755-773 ---
        } else if (strcmp(type->valuestring, "llm") == 0) {
            auto emotion = cJSON_GetObjectItem(root, "emotion");
            if (cJSON_IsString(emotion)) {
                Schedule([this, display, emotion_str = std::string(emotion->valuestring)]() {
                    // Live2D: the server sends an emotion with the LLM reply and often
                    // keeps sending more during the TTS stream. Showing one while
                    // speaking would replace the speaking.gif mouth animation with a
                    // still (sometimes eyes-closed) face, so keep the animation alive
                    // until the speaking state ends. Do not re-set the emotion here:
                    // SetEmotion() restarts the GIF controller from frame 0.
                    auto state = GetDeviceState();
                    if (state == kDeviceStateSpeaking || state == kDeviceStateNotifying) {
                        ESP_LOGI(TAG, "Skip server emotion '%s' while speaking",
                                 emotion_str.c_str());
                        return;
                    }
                    display->SetEmotion(emotion_str.c_str());
                });
            }

// --- application.cc:861-869 ---
void Application::DismissAlert() {
    last_error_message_.clear();
    if (GetDeviceState() == kDeviceStateIdle) {
        auto display = Board::GetInstance().GetDisplay();
        display->SetStatus(Lang::Strings::STANDBY);
        SetCharacterEmotion(display, "idle");
        display->SetChatMessage("system", "");
    }
}

// --- application.cc:1104-1159 ---
    switch (new_state) {
        case kDeviceStateUnknown:
        case kDeviceStateIdle:
            // Keep a just-raised network error visible. SetDeviceState(idle)
            // queues STATE_CHANGED after Alert(), and the idle handler would
            // otherwise wipe the status, emotion, and chat message.
            if (last_error_message_.empty()) {
                display->SetStatus(Lang::Strings::STANDBY);
                display->ClearChatMessages();  // Clear messages first
                // Then set emotion (wechat mode checks child count)
                SetCharacterEmotion(display, "idle");
            }
            audio_service_.EnableVoiceProcessing(false);
            audio_service_.EnableWakeWordDetection(true);
            break;
        case kDeviceStateConnecting:
            display->SetStatus(Lang::Strings::CONNECTING);
            SetCharacterEmotion(display, "idle");
            display->SetChatMessage("system", "");
            break;
        case kDeviceStateListening:
            display->SetStatus(Lang::Strings::LISTENING);
            SetCharacterEmotion(display, "idle");

            // Make sure the audio processor is running
            if (play_popup_on_listening_ || !audio_service_.IsAudioProcessorRunning()) {
                // For auto mode, wait for the playback queue to drain before enabling
                // voice processing. This prevents audio truncation when STOP arrives
                // late due to network jitter. Instead of blocking the main loop here,
                // defer the start until MAIN_EVENT_PLAYBACK_DRAINED arrives.
                if (listening_mode_ == kListeningModeAutoStop && !audio_service_.IsPlaybackIdle()) {
                    pending_listening_start_ = true;
                } else {
                    StartListeningAudio();
                }
            } else {
                ConfigureWakeWordForListening();
            }
            break;
        case kDeviceStateSpeaking:
            display->SetStatus(Lang::Strings::SPEAKING);
            SetCharacterEmotion(display, "speaking");

            if (listening_mode_ != kListeningModeRealtime) {
                audio_service_.EnableVoiceProcessing(false);
                // Only AFE wake word can be detected in speaking mode
                audio_service_.EnableWakeWordDetection(audio_service_.IsAfeWakeWord());
            }
            audio_service_.ResetDecoder();
            break;
        case kDeviceStateNotifying:
            display->SetStatus(Lang::Strings::SPEAKING);
            SetCharacterEmotion(display, "speaking");
            audio_service_.EnableVoiceProcessing(false);
            audio_service_.EnableWakeWordDetection(audio_service_.IsAfeWakeWord());
            break;

