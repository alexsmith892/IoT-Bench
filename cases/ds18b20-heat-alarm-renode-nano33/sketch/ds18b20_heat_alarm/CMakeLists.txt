cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(ds18b20_heat_alarm)

file(GLOB app_sources CONFIGURE_DEPENDS src/*.c)
target_sources(app PRIVATE ${app_sources})
