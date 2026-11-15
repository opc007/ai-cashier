#pragma once

// Optional 2D character module (云天 / yuntian365 live2d pack).
// Off unless the firmware build defines XIAOZHI_LIVE2D_CHARACTER=1
// (CMake option of the same name) or Kconfig CONFIG_XIAOZHI_LIVE2D_CHARACTER.
// Stock cashier emotion behavior stays in place while this is 0.

#if !defined(XIAOZHI_LIVE2D_CHARACTER)
#  if defined(CONFIG_XIAOZHI_LIVE2D_CHARACTER)
#    define XIAOZHI_LIVE2D_CHARACTER 1
#  else
#    define XIAOZHI_LIVE2D_CHARACTER 0
#  endif
#endif
