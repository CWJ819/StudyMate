from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'tests' / 'fixtures' / 'f1-sample.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open()
p1 = doc.new_page()
p1.insert_text((72, 96), '第3章 运输层', fontsize=20, fontname='china-s')
p1.insert_text((72, 140), 'TCP 拥塞控制：慢启动与拥塞避免', fontsize=12, fontname='china-s')
p1.insert_text((72, 158), '慢启动阶段：拥塞窗口 cwnd 从 1 个 MSS 起步，每收到一个 ACK，cwnd 增加 1 个 MSS，', fontsize=11, fontname='china-s')
p1.insert_text((72, 174), '因此每经过一个 RTT，cwnd 翻倍，呈指数增长。', fontsize=11, fontname='china-s')
p1.insert_text((72, 192), '当 cwnd 达到慢启动门限 ssthresh 后，进入拥塞避免阶段，cwnd 按线性增长。', fontsize=11, fontname='china-s')
p1.insert_text((72, 210), '发生超时则门限减半并重新慢启动；收到 3 个重复 ACK 触发快重传与快恢复。', fontsize=11, fontname='china-s')
p2 = doc.new_page()  # 只有图形，无可提取文本
p2.draw_circle((300, 400), 60, color=(0.2, 0.4, 0.7), width=3)
p3 = doc.new_page()
p3.insert_text((72, 96), '可靠传输：GBN 与 SR', fontsize=16, fontname='china-s')
p3.insert_text((72, 130), '回退 N 步（GBN）通过累计确认重传从旧分组起的所有分组；', fontsize=11, fontname='china-s')
p3.insert_text((72, 148), '选择重传（SR）只重传真正丢失的分组，接收方逐个确认。', fontsize=11, fontname='china-s')
p3.insert_text((72, 166), '滑动窗口机制：发送窗口 = min(cwnd, rwnd)。', fontsize=11, fontname='china-s')
doc.save(str(OUT))
print('saved:', OUT)
print('pages:', doc.page_count)
