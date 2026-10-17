/* The C interface of the mestra core: the one surface every binding
 * (Python, MATLAB, Julia) and C or C++ caller uses.  Opaque handles,
 * caller-allocated buffers, UTF-8 strings, and an error record on every
 * failure.  No C++ type and no HDF5 identifier crosses it.
 *
 * Every function returning int returns 0 on success and nonzero on
 * failure, when it fills *err if err is not NULL.  No function keeps a
 * pointer the caller passed after it returns.
 */
#ifndef MESTRA_H
#define MESTRA_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  if defined(MESTRA_BUILDING)
#    define MES_API __declspec(dllexport)
#  else
#    define MES_API __declspec(dllimport)
#  endif
#else
#  define MES_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* An error: the rule of spec section 16 when one applies ("E7"), a
 * concept path ("node_fields/p") when one applies, and a message. */
typedef struct {
  char rule[8];
  char path[512];
  char message[2048];
} mes_error;

/* Element types; the numbers are fixed. */
enum {
  MES_UINT8 = 1,
  MES_INT8 = 2,
  MES_INT32 = 3,
  MES_INT64 = 4,
  MES_FLOAT32 = 5,
  MES_FLOAT64 = 6
};

/* A selection along one axis. */
enum { MES_SEL_ALL = 0, MES_SEL_RANGE = 1, MES_SEL_INDEX = 2 };
typedef struct {
  int kind;
  int64_t start, stop;     /* MES_SEL_RANGE: [start, stop) */
  const int64_t* index;    /* MES_SEL_INDEX: strictly increasing */
  int64_t count;
} mes_sel;

/* The library's version ("1.0.0.dev0") and the format string it writes
 * ("mestra/1").  Static strings; never freed. */
MES_API const char* mes_version(void);
MES_API const char* mes_format(void);

#ifdef __cplusplus
}
#endif

#endif /* MESTRA_H */
