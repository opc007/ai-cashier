#pragma once

// Callable 2D character helper for the v2.5.2 tree.
// Upstream (v2.5.3) wrote `if (display->SetEmotion(emotion))`. That does not
// compile here: Display::SetEmotion is void and a missing name falls through
// to a font glyph, so it cannot report "the live2d GIF was shown".
// SetEmojiEmotion() is the v2.5.2 bridge: true only when an emoji-collection
// image was shown. Failure falls back to SetEmotion("neutral").

#include "character_emotion_config.h"
#include "character_emotion_logic.h"
#include "display.h"

#include <esp_log.h>

template <typename DisplayPtr>
void SetCharacterEmotion(DisplayPtr display, const char* emotion) {
    if (display == nullptr || emotion == nullptr) {
        return;
    }
    if (display->SetEmojiEmotion(emotion)) {
        ESP_LOGI("CharacterEmotion", "Character emotion: %s", emotion);
    } else {
        display->SetEmotion("neutral");
    }
}
