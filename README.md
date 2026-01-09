# Portable Incremental Backup Tool

**Yazar:** Sergen Başakçı  
**Platform:** Windows (Linux uyumlu – VSS hariç)  
**Dil:** Python 3  
**Arayüz:** PyQt6  

---

## 1. Proje Amacı

Bu projenin amacı; taşınabilir (portable), artımlı (incremental) yedekleme yapabilen,
GUI ve CLI destekli bir masaüstü yedekleme yazılımı geliştirmektir.

Uygulama;
- Belirlenen klasörlerin yedeğini alır,
- Aynı dosyayı birden fazla kez kopyalamaz,
- Zaman bazlı snapshot’lar oluşturur,
- İstenilen snapshot’tan geri yükleme yapabilir.

---

## 2. Temel Özellikler

- ✅ Artımlı yedekleme (content-addressed storage)
- ✅ Snapshot tabanlı yedekleme
- ✅ GUI (PyQt6) + CLI desteği
- ✅ Geri yükleme (restore)
- ✅ Bütünlük doğrulama (verify)
- ✅ Windows Volume Shadow Copy (opsiyonel)
- ✅ Portable EXE üretimi (PyInstaller)

---

## 3. Mimari Yapı

Proje modüler olarak tasarlanmıştır.

