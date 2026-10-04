# Gateway trust boundaries — tasarım notu

Bu not gelecekteki tool/RAG entegrasyonları için tasarımdır. Retrieval, tool
execution, ActionGuard, tenant/ACL denetimi ve semantik output policy mevcut
üründe uygulanmış özellikler değildir.

## Mevcut runtime

```text
Rate/body limit → RuleGuard + SemanticGuard v2 → benign-intent adapter → Policy
    BLOCK → provider çağrısı olmadan cevap
    ALLOW → deadline + admission → AsyncGroq → response validation → DataGuard → cevap
```

Mevcut API tek user mesajı ve metin cevabı destekler. DataGuard yalnızca
provider çıktısındaki desteklenen hassas formatları redakte eder; kullanıcı
girdisini provider'a göndermeden önce redakte etmez. Client authentication
yerleşik değildir. Ayrıntılar için [README](../README.md) ve
[provider admission](PROVIDER_ADMISSION.md) belgelerine bakın.

## Önerilen kaynak güven modeli

Aşağıdaki tablo mevcut input/output guard'ları ile gelecekte uygulanması
gereken kaynak, yetki ve audit kontrollerini birlikte açıklar. Doküman/tool
kaynak türü ve ActionGuard kayıtları mevcut audit şemasının özellikleri değildir.

| Kaynak | Güven düzeyi | Guard / kontrol | Injection riski | Action izni | Audit/log |
|---|---|---|---|---|---|
| A. User input | Kimliği/rolü doğrulansa bile metin güvenilmez; yalnızca kullanıcı seviyesinde istek | Mevcut RuleGuard → SemanticGuard v2 → Policy; boyut/rate limit. Provider'a secret gönderimini ayrıca değerlendirmek gerekir | Doğrudan jailbreak, yetki iddiası, role spoofing | Kullanıcı metni yetki vermez; kimlik, tenant ve kaynak bazında izin gerekir | Request ID, kaynak türü, guard skoru/kararı/süresi; ham metin yok |
| B. Retrieved document | Güvenilmez veri; ACL erişimi talimat yetkisi sağlamaz | Retrieval öncesi tenant/ACL; provenance; ayrı indirect-injection taraması; uzun içerikte kapsama/chunk kontrolü. Mevcut v2 bu bağlam için doğrulanmış değil | Gizli talimat, kaynak dışına veri gönderme, araç yönlendirme | Doküman hiçbir action'ı yetkilendiremez | Doküman ID/sürüm, erişim kararı, taranan bölüm sayısı, skor; raw içerik yok |
| C. Tool output | Araç allowlist'te olsa bile dönen içerik güvenilmez veri | Response schema, boyut/süre, provenance; indirect-injection taraması; hassas veri egress kontrolü | Tool sonucunda role spoofing, ikinci tool çağrısı isteği, dış URL/secret sızıntısı | Tool sonucu yeni izin veya kullanıcı onayı yaratmaz | Tool adı/çağrı ID, status, policy ve schema sonucu, süre; raw argüman/output yok |
| D. System/developer instruction | Yalnızca sunucu kontrolündeki sürümlenmiş yapılandırma yetkili | Kaynak doğrulama, değişiklik incelemesi, sürüm/integrity kontrolü. Güvenilmez kaynaklardan bu role yükseltme yasak | Şablona güvenilmez talimat ekleme, yanlış role yerleştirme | Talimatlar araç capability üst sınırını tanımlar; sunucu authorization yine zorunlu | Policy/template sürümü; ham system prompt veya secret yok |
| E. Model output | Güvenilmez üretilmiş veri | Provider response validation → DataGuard; gelecekte ayrı semantik output policy. Tool çağrıları için schema + ActionGuard | Hassas veri, zararlı içerik, beklenmeyen action/argüman | Model tool seçimi yalnızca öneridir; execute öncesi sunucuda yetki denetimi | Output finding türü/sayısı, action, tool izin sonucu, süre; raw cevap yok |

## Gelecekteki RAG/tool entegrasyonu için önerilen sıra

```text
User input → mevcut input guard'lar → Policy
                   ↓ ALLOW
RAG retrieval / tool result → ACL + provenance + indirect-content checks
                   ↓ yalnızca veri
Server-owned system/developer instructions + user request + typed source data
                   ↓
Provider → response validation → DataGuard → output policy → Response
                   ↓ tool action önerisi varsa
Schema validation → ActionGuard(identity/tenant/tool/resource/arguments)
                   ↓ izin verilirse
Tool execution → sonuç tekrar güvenilmez veri sınırına
```

Retrieved document ve tool output, user instruction gibi kabul edilmez; system/developer role'e asla aktarılmaz. Prompt'ta ayrı veri alanı ve provenance tutulur. Delimiter veya 'bu talimatları takip etme' cümlesi tek başına güvenlik sınırı değildir; enforcement server-side izin ve egress kontrolüdür.

ActionGuard varsayılanı deny olmalı: tool allowlist, tenant/resource ACL, argüman schema ve path/URL hedef sınırı, read/write ayrımı, maliyet/çağrı bütçesi. Hassas veya irreversible action için onay, user inputtan veya dokümandan değil doğrulanmış server-side approval kaydından gelmeli. Kullanıcı yetki talebi ('adminim') veya model confidence izin yerine geçmez.

Source taraması başarısız/eksik olduğunda source kullanılmamalı; yetki kontrolü hatasında action çalışmamalı. Tarama ve action izin kayıtları aynı request ID ile ilişkilendirilmeli. Ham prompt/document/tool output/cevap, token veya düşük seviyeli exception detayı persist edilmemeli.

Mevcut gateway yalnızca tek user mesajı ve metin cevabı destekliyor. Bir indirect-injection fixture'ının bloklanmış olması bu tasarımın uygulandığını kanıtlamaz.
