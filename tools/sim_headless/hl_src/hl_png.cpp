//[HEADLESS] separate, optimized TU for PNG encoding (sim.cpp is built /Od). A static stb copy avoids symbol clashes.
#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif
#pragma warning(disable: 4505 4100 4244 4456 4457 4245 4701 4703)
#define STB_IMAGE_WRITE_STATIC
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

int hl_png_write(const char* path, int w, int h, const unsigned char* rgb)
    {
        stbi_write_png_compression_level = 1;
        return stbi_write_png(path, w, h, 3, rgb, w * 3);
    }
