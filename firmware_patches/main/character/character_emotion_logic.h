#pragma once

#include "device_state.h"

// State map from yuntian365/xiaozhi-p4-dfrobot (v2.5.3 application.cc),
// kept as plain functions so ai-cashier v2.5.2 can call them without taking
// the v2.5.3 SetEmotion() bool return value.
//
//   idle / unknown / connecting / listening -> "idle"     (breath + blink GIF)
//   speaking / notifying                    -> "speaking" (mouth GIF)
//   anything else                           -> nullptr    (leave the face alone)
//
// Server "llm" emotion packets are dropped while speaking or notifying.
// Applying them would replace speaking.gif with a still (often eyes-closed)
// and SetEmotion() would restart the GIF from frame 0 on every clause.

inline const char* CharacterEmotionNameForState(DeviceState state) {
    switch (state) {
        case kDeviceStateUnknown:
        case kDeviceStateIdle:
        case kDeviceStateConnecting:
        case kDeviceStateListening:
            return "idle";
        case kDeviceStateSpeaking:
        case kDeviceStateNotifying:
            return "speaking";
        default:
            return nullptr;
    }
}

inline bool CharacterEmotionAcceptsServerEmotion(DeviceState state) {
    return state != kDeviceStateSpeaking && state != kDeviceStateNotifying;
}
