#!/usr/bin/env python3
"""兼容入口：只评分单轮模型输出。"""

from score_outputs import main


if __name__ == "__main__":
    raise SystemExit(main("single"))
