# Sık Sorulan Sorular

En çok sorulan konulara kısa yanıtlar. Sorunuz burada yoksa alt bilgideki **Geri Bildirim** bağlantısına tıklayın ve bize Discord üzerinden sorun.

## Smart Citizen'ın yaptığı değişiklikleri nasıl geri alırım?

Kolayca ve istediğiniz zaman. Smart Citizen oyunun orijinal dosyalarını hiçbir zaman yerinde düzenlemez; bu yüzden orijinal haline dönmek tek tıkla olur:

- **Araç çubuğu → Daha Fazla → Yerelleştirmeyi Temizle**, Smart Citizen'ın yazdığı özel `global.ini` dosyasını siler. Oyun hemen kendi yerleşik metnine döner. Düzenlemeleriniz kaybolmaz; uygulamada kayıtlı kalır ve istediğiniz zaman yeniden uygulayabilirsiniz.
- Tamamen geri dönmek yerine yalnızca bir sürüm geriye gitmek mi istiyorsunuz? **Araç çubuğu → Daha Fazla → Yedeği Geri Yükle**, oyun dosyasını zaman damgalı bir yedeğe geri döndürür (Smart Citizen son 5 yedeği saklar ve her Uygula işleminde yeni bir yedek oluşturur).

Kişisel düzenlemeleriniz, oyundan ayrı olarak Smart Citizen veri klasörünüzdeki `user.ini` dosyasında bulunur; bu nedenle oyun dosyasını temizlemek onlara hiçbir zaman dokunmaz.

## Smart Citizen kullandığım için yasaklanır mıyım?

Smart Citizen yalnızca yerelleştirme metnini (oyunun size gösterdiği sözcükleri) düzenler; oyun mantığına dokunmaz, size herhangi bir avantaj sağlamaz ve CIG'in sunucularıyla iletişim kurmaz. Değişikliklerimiz sorun yaratmamalıdır **diye düşünüyoruz**.

CIG, topluluk yerelleştirmesini açıkça desteklemiştir. [Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) gönderisi, oyuncular tarafından yapılan çevirilere yönelik resmi desteği ortaya koyar; bizim anladığımız kadarıyla bu, Smart Citizen'ın yaptığı türden yerelleştirme düzenlemelerine açıkça izin vermektedir.

Tanınmış yayıncılar benzer yerelleştirme projelerini herkesin gözü önünde yürütüyor ve hiçbirine durması söylenmedi.

Yine de: Smart Citizen'ı nasıl kullandığınız kendi sorumluluğunuzdadır. Bizim değişikliklerimiz sorun yaratmamalıdır; ancak kendi yaptığınız her şey için oluşabilecek zararlardan siz ve birlikte hareket ettiğiniz kişiler sorumludur. Bir değişikliğin uygun olup olmadığından emin değilseniz, değişikliği kozmetik düzeyde tutun ve bir yedek saklayın.

## Smart Citizen hangi dosyaları değiştirir?

Yalnızca birini ve yalnızca **Geliştirmeleri Uygula**'ya tıkladığınızda:

- `StarCitizen\<kanal>\data\Localization\<dil>\global.ini` — seçtiğiniz kanal (LIVE, PTU vb.) ve dil için oyunun yerelleştirme dosyası. Smart Citizen önce mevcut dosyayı yedekler, ardından birleştirilmiş sonucu yazar.
- Ayrıca oyunun doğru yerelleştirmeyi yüklemesi için `user.cfg` dosyanızda `g_language` değerinin ayarlı olduğundan emin olur. Oyun kurulumunuzdaki başka hiçbir şeye dokunulmaz.

Smart Citizen'ın kendi kullanımı için oluşturduğu her şey (kaynak önbelleği, geliştirme dosyaları, yedekler, `user.ini` dosyanız) oyunda değil, Smart Citizen veri klasörünüzde bulunur.

## Windows neden bu uygulamanın tanınmadığını söylüyor?

Çünkü Smart Citizen henüz kod imzalı değil. Windows SmartScreen ve Smart App Control, imza sertifikası kayıtlarında bulunmayan bir yayıncının her yeni uygulamasını, tamamen güvenli olsa bile işaretler. Bu bir "bunu daha önce görmedik" uyarısıdır, "bu tehlikeli" uyarısı değil.

Çalıştırmak için: SmartScreen isteminde **Daha fazla bilgi → Yine de çalıştır**'a tıklayın. Smart App Control uygulamayı tamamen engelliyorsa, kendi isteminden uygulamaya izin verebilir ya da Smart App Control'ü geçici olarak kapatıp kurulumu yapabilir ve sonra yeniden açabilirsiniz.

Kod imzalama yol haritamızda yer alıyor; bu uyarı o zaman ortadan kalkacak. O zamana kadar Smart Citizen'ı yalnızca resmi GitHub sürümlerimizden indirin; böylece elinizdeki yapının orijinal olduğundan emin olursunuz.
