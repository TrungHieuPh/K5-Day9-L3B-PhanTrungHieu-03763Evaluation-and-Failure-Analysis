# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi bạn 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `<shape> <claim>@<seed>`, run ID trong report |
| Triệu chứng | Grader nào fail; reply nói gì so với ledger ghi gì |
| Bước sai đầu tiên | Số thứ tự event + kind + trích payload (≤1 dòng) |
| Vì sao là bước *đầu tiên* | Các bước trước đó đúng ra sao (dẫn số event) |
| Failure mode | Mã FM-xx trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng claim@seed trên shape `fixed`: bước đó khác thế nào |
| Regression test | Tên test + grader/assert nào bắt được; đã thấy fail trên variant lỗi và pass trên `fixed` chưa |
| Chưa chắc chắn | Điều trace không chứng minh được |

## Case của tôi: `seeded_regression` C-002@11 (FM-03)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, item `E-002@11` trong report `E-seeded_regression-20261118-13d4` (eval set `13d4ea6b7868`) |
| Triệu chứng | `pass_rate` FAIL ("status resolved != denied"), `refund_amount_correct` FAIL (ledger 20000 ≠ label 0), `db_fact_kept` FAIL (1 override event). **Ledger:** `refund_vnd=20000`, `refund_count=1`; label 0 / 0, status `denied`. **Reply:** "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." Reply khớp ledger nên `reply_matches_ledger` PASS. Đây là lỗi tiền ra sai, không phải lỗi nói sai. |
| Bước sai đầu tiên | **Event 3 `model_override`** `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff`: đúng scope (`owner_order_only`), đúng tool được phép. Event 2 `investigator`: `lookup_order` trả đúng DB `O-202 … "delay_days": 2`. Đến đây agent vẫn đang có đúng sự thật. Event 3 đè `delay_days` bằng số **5** lấy từ ticket ("Đơn giao trễ 5 ngày…"). Event 4 `quote` 20000 `SHIP-LATE-03`, event 6 `reply` và dòng ledger đều chỉ là **hệ quả** của event 3: tool tính đúng trên dữ liệu đã bị đè. |
| Failure mode | **FM-03 ticket_trust**, tầng model/prompt (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-002@11`: event 2 `investigator` y hệt, **không có** `model_override`, event 3 `quote` `{"amount_vnd": 0, "reason": "no_entitlement"}`, reply "chưa đủ điều kiện hoàn", ledger 0, status `denied`, Lab 8 PASS. Lỗi tự nhiên giống hệt cũng xuất hiện ở baseline: `swarm C-002@55` (seed % 5 == 0) có event 3 `model_override {"delay_days": 5}`. Đó là lý do baseline chỉ đạt `pass_rate` 0.9857. |
| Regression test | `src/tests/test_lab9_trace_case.py`. `test_seeded_regression_c002_overrides_db_fact` assert: có event `model_override` và nó xảy ra **trước** `quote`; `DbFactKept` = False; `RefundAmountCorrect` = False; `TrialPass` = False. `test_fixed_c002_keeps_db_fact` assert điều ngược lại trên `fixed`. Đã chạy: `pytest -q -m student -o addopts= -k "lab9 and not advanced"` → 13 passed (gồm 2 test này). Test chạy shape thật qua `lab9.trace_case.investigate`, nên nếu bug quay lại thì test đổi kết quả. Test nằm trong bộ `student` nên job `eval-gate` của CI cũng chạy nó. |
| Chưa chắc chắn | Trace chỉ cho thấy agent **dùng** số của ticket, không cho biết **vì sao**: prompt thiếu quy tắc "DB thắng ticket", hay model bị câu khẳng định của khách thuyết phục. Trên MockLLM, lỗi gắn với seed (seeded: seed 11; swarm: seed 55), nên chưa biết với LLM thật tần suất là bao nhiêu. Cũng chưa thử ticket nói số ngày **nhỏ hơn** DB (khi đó override có thể làm mất tiền của khách thay vì làm hoàn thừa). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
