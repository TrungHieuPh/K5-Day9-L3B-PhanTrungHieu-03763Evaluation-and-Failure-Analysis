# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`
Lớp dương (positive) = `FAIL`: việc của judge là **tìm ra** reply hỏng.

| Tiêu chí | n | κ | Precision | Recall | Ma trận (tp/fp/fn/tn) | Tỉ lệ FAIL quan sát → hiệu chỉnh RG | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | 24 / 4 / 6 / 66 | 0.28 → 0.30 | **PASS** (exit 0) | **dùng** (non-blocking, chỉ cho giọng văn) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | 9 / 0 / 21 / 70 | 0.09 → 0.30 | **FAIL** (κ < 0.6, R < 0.7; exit 1) | **loại**, không dùng làm gate |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | **Người** | Xưng "em", "nha" quá suồng sã. Rubric thêm: bắt buộc xưng "LogiX" / "anh/chị", cấm "em", "nha", "bạn ơi". |
| 2 | H-029 "Dạ, vui lòng chờ… không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ thấy từ lịch sự "Dạ, vui lòng", bỏ qua giọng ra lệnh. Rubric thêm: câu mệnh lệnh / chặn khách liên hệ ⇒ FAIL dù có kính ngữ. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì thiếu xin lỗi. Rubric ghi rõ: xin lỗi **không bắt buộc**; ngắn mà đủ ý, lịch sự là PASS. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | **Người** | Style guide CS LogiX cho phép "refund". Rubric thêm whitelist thuật ngữ tiếng Anh được phép. |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket) ⇒ **sửa nhãn người**, không sửa rubric. Bất đồng không phải lúc nào cũng là lỗi judge. |
| 6 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm…" | PASS | FAIL | **Người** | Hứa ngoài kết quả hệ thống. Đây là lỗi nội dung (gần FM-08), không phải giọng văn ⇒ chấm bằng code so reply với ledger, không giao cho judge tone. |
| 7 | H-070 "…cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Rubric thêm: emoji cười trong ngữ cảnh khiếu nại ⇒ FAIL. |
| 8 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | **Người** | Rubric thêm: tiếng Việt mất dấu / dịch máy ⇒ FAIL. |
| 9 | HL-015 "Dạ, LogiX đã hoàn 55.000đ…" (ledger 40.000đ) | PASS | FAIL | **Người** | Judge helpful **không thấy ledger** nên không thể biết số tiền sai. 18/21 FN của helpful là kiểu này (3 FN còn lại là reply "Ok bạn, … xử lý rồi nhé") ⇒ phải chấm bằng code (metric FM-08), không bằng judge. |
| 10 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Không nói kết quả, không nói số tiền ⇒ không hữu ích. Judge helpful bỏ qua cả reply thiếu thông tin. |

## Kết luận
- **`helpful` bị loại.** Ma trận 9/0/21/70: judge gần như không bao giờ nói FAIL (chỉ 9/100). Precision = 1.0 trông đẹp nhưng vô nghĩa, vì Recall = 0.3 tức là **bỏ sót 21/30 reply hỏng** (70%). κ = 0.375 < 0.6. Tỉ lệ FAIL quan sát 9% nhưng sau hiệu chỉnh Rogan-Gladen là **30%**: dùng judge này làm gate sẽ báo agent tốt gấp ~3 lần thực tế. Phần lớn lỗi nó bỏ sót là **số tiền trong reply khác ledger**, loại lỗi mà judge không thể thấy vì không đọc ledger. Theo quy tắc taxonomy, tiền luôn chấm bằng code ⇒ thay bằng metric FM-08 (M3).
- **`tone_ok` được dùng**, nhưng chỉ như metric **non-blocking** cho giọng văn: κ 0.757, P 0.857, R 0.8 đều qua sàn. Vẫn còn 6 FN (bỏ sót giọng suồng sã/ra lệnh/emoji/mất dấu) và 4 FP; sửa rubric như bảng trên rồi calibrate lại. Tỉ lệ FAIL thật ước tính 30% (RG) so với 28% quan sát, lệch nhỏ.
- Bất đồng không tự động là lỗi judge: H-081 là nhãn người sai ⇒ sửa nhãn.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng/tiêu chí); cần nhãn người mới để có held-out thật, và sửa rubric xong phải đo lại trên tập chưa thấy (không tối ưu rubric trên chính 100 dòng này).
