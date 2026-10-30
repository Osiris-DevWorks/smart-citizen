# Smart Citizen — Yasal Bilgiler ve Uyumluluk

Bu sayfa, Smart Citizen'a ilişkin tüm yasal, lisans ve veri işleme bildirimlerini tek bir yerde toplar. Burada yer alan bir husus, yürütülebilir dosyanın yanında sunulan `LICENSE` veya `NOTICE` dosyalarıyla çelişirse bu dosyalar esas alınır.

*Bu belge bir çeviridir; herhangi bir farklılık durumunda İngilizce `docs/LEGAL.md` sürümü esas alınır.*

## Star Citizen / Cloud Imperium Bildirimi

Smart Citizen, Star Citizen için **resmî olmayan bir topluluk aracıdır**. Cloud Imperium Games (CIG) veya Roberts Space Industries (RSI) tarafından geliştirilmemiştir, onaylanmamıştır, desteklenmemiştir ve bunlarla hiçbir şekilde bağlantılı değildir. Smart Citizen, CIG'nin hayranlar tarafından üretilen içerik ve araçlara yönelik "Made by the Community" (Topluluk Tarafından Yapıldı) yönergeleri kapsamındadır.

**Star Citizen®**, **Roberts Space Industries®** ve **Cloud Imperium®**, Cloud Imperium Rights LLC ve Cloud Imperium Rights Ltd'nin tescilli ticari markalarıdır. `Data.p4k` içeriği, gemi ve bileşen modelleri, eşya adları, görev metinleri ve evren hikâyesi dahil tüm Star Citizen oyun verileri Cloud Imperium Rights LLC'nin fikri mülkiyetidir.

Smart Citizen hiçbir CIG veya RSI içeriğini yeniden dağıtmaz. Uygulama, yerel bilgisayarınızdaki **kendi lisanslı Star Citizen kurulumunuzdan** dosyaları okur ve kullanıcı tarafından özelleştirilmiş metinleri aynı kuruluma geri yazar. CIG'ye ait hiçbir içerik Smart Citizen aracılığıyla bilgisayarınızdan dışarı çıkmaz.

## Smart Citizen Lisansı

Smart Citizen, **Apache License, Version 2.0** kapsamında lisanslanmış açık kaynaklı bir yazılımdır. Lisansın bir kopyasını [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0) adresinden edinebilirsiniz. Lisans metninin tamamı, yürütülebilir dosyanın yanındaki `LICENSE` dosyasında sunulur; kaynak kodu ise [GitHub deposunda](https://github.com/Osiris-DevWorks/smart-citizen) mevcuttur.

Yürürlükteki yasaların gerektirdiği veya yazılı olarak kararlaştırıldığı durumlar dışında, Lisans kapsamında dağıtılan yazılım, açık ya da zımni **hiçbir tür garanti veya koşul olmaksızın "OLDUĞU GİBİ" esasıyla** dağıtılır. İzinleri ve sınırlamaları düzenleyen özel hükümler için Lisansa bakınız.

## Paketle Sunulan Üçüncü Taraf Yazılımlar

Smart Citizen, yükleyicisi içinde aşağıdaki üçüncü taraf yazılımları sunar. Her birinin tam atıf metni, yürütülebilir dosyanın yanındaki `NOTICE` dosyasındadır.

- **unp4k / unforge** — `assets/unp4k/` altında `unp4k.exe` ve `unforge.exe` olarak paketlenmiştir. Osiris DevWorks, özgün [dolkensp/unp4k](https://github.com/dolkensp/unp4k) projesinin paralel çıkarma ve performans iyileştirmeleri içeren kendi çatallamasını ([odw-fast-unp4k](https://github.com/Osiris-DevWorks/odw-fast-unp4k)) sunar. `Data.p4k` dosyasını açmak ve DataForge varlık dosyalarını XML'e dönüştürmek için kullanılır. **MIT License** kapsamında lisanslanmıştır.
- **PyQt6** — Riverbank Computing tarafından geliştirilen arayüz çerçevesi. Ticari olmayan dağıtım için **GNU General Public License v3 (GPL-3.0)** kapsamında kullanılır; Riverbank'tan ticari lisans da edinilebilir. Smart Citizen ücretsiz, açık kaynaklı bir topluluk aracıdır ve GPL-3.0 koşullarını karşılar.
- **lxml** — lxml.de tarafından geliştirilen XML ayrıştırma kütüphanesi. **BSD-3-Clause License** kapsamında kullanılır.

Python standart kütüphanesi ve PyInstaller tarafından paketlenen diğer çalışma zamanı bağımlılıkları kendi lisanslarına tabidir; bkz. Python Software Foundation License: [docs.python.org/3/license.html](https://docs.python.org/3/license.html).

## Gizlilik ve Veri İşleme

Smart Citizen **yerel bir masaüstü uygulamasıdır**. Düzenlemelerinizi, `user.ini` dosyanızı, `base.ini` dosyanızı, özelleştirmelerinizi veya bilgisayarınızdaki başka herhangi bir içeriği Osiris DevWorks'ün ya da herhangi bir üçüncü tarafın işlettiği bir sunucuya iletmez.

### Bilgisayarınızda kalanlar

Her şey. Yerelleştirme düzenlemeleriniz, yedekleriniz, uygulama ayarlarınız ve DataForge önbelleğiniz yalnızca yerel diskinizde bulunur:

- **Ayarlar** — Varsayılan kurulumda `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` altındaki Windows Kayıt Defteri; taşınabilir sürümde ise yürütülebilir dosyanın yanındaki `config.json`.
- **Kullanıcı düzenlemeleri + yedekler** — Varsayılan olarak `Documents\Smart Citizen\{channel}\` (Yapılandırma sekmesinden yapılandırılabilir; taşınabilir sürüm bunun yerine `<exe-dir>\data\` kullanır).
- **DataForge XML önbelleği** — `%LOCALAPPDATA%\Smart Citizen\{channel}\cache\dataforge\`.
- **Çökme dökümleri + elle yapılan günlük dışa aktarımları** — `Documents\Smart Citizen\logs\` (veya taşınabilir sürümdeki karşılığı); yalnızca uygulama çöktüğünde veya Günlük sekmesinde *Dosyaya aktar…* düğmesine tıkladığınızda yazılır.

### Ağ üzerinden gidenler

Smart Citizen yalnızca üç durumda giden ağ isteği yapar:

- **Güncelleme denetimi** — Kurulu sürümü en son GitHub sürümüyle karşılaştırmak için yaklaşık 6 saatte bir `api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest` adresine yapılan küçük, kimlik doğrulamasız bir istek. Yalnızca sürüm meta verilerini (etiket adı, sürüm URL'si) döndürür; hiçbir Smart Citizen durumu gönderilmez.
- **Dil indirmeleri** — İngilizce dışında bir dile geçtiğinizde Smart Citizen, o dilin topluluk tarafından çevrilmiş `global.ini` dosyasını yapılandırılmış URL'den (varsayılan olarak [Dymerz/StarCitizen-Localization](https://github.com/Dymerz/StarCitizen-Localization) GitHub deposundan) indirir. İndirme yerel olarak önbelleğe alınır; bilgisayarınızdan hiçbir şey gönderilmez.
- **Kullanıcı tarafından yapılandırılan uzak kaynaklar** — Yapılandırma sekmesinde bir `http(s)://` URL'sine işaret eden bir veri kaynağı yapılandırdıysanız Smart Citizen, kaynak dosyalarını yenilerken bu URL'yi alır. Kurulum sonrası varsayılan durumda bu yalnızca `global` kaynağının GitHub-raw URL biçimi için geçerlidir; v1.0'dan bu yana standart yapılandırma `base.ini` dosyasını bunun yerine yerel Data.p4k çıkarımınızdan okur.

### Smart Citizen'ın **yapmadığı** şeyler

- Hiçbir türde telemetri, analiz veya kullanım raporlaması yoktur.
- Kişisel olarak tanımlanabilir hiçbir bilgi toplanmaz, saklanmaz veya iletilmez.
- Arka planda veri yükleme yoktur.
- Uzak bir sunucuya otomatik çökme raporlaması yoktur — çökme dökümleri **yalnızca yerel olarak** `Documents\Smart Citizen\logs\` altına yazılır. Bir hata bildirimi için bunlardan birini paylaşmak isterseniz dosyayı kendiniz kopyalayıp yapıştırırsınız.
- Hesap yok, oturum açma yok, uzak kimlik yok.

Yukarıdakilerle çelişen bir davranış tespit ederseniz lütfen [github.com/Osiris-DevWorks/smart-citizen/issues](https://github.com/Osiris-DevWorks/smart-citizen/issues) adresinden bir hata bildirimi açın.

## Yapay Zekâ Kullanımı Beyanı

Smart Citizen kaynak kodunun bazı bölümleri, Anthropic'in yapay zekâ kodlama asistanı **Claude**'un yardımıyla yazılmıştır. Üretilen kod, **birleştirilmeden önce insan bir proje yürütücüsü tarafından incelenir ve onaylanır** — yapay zekâ doğrudan commit yapmaz ve diğer tüm kod katkılarıyla aynı şekilde ele alınır: okunur, test edilir ve yalnızca kendi değeri üzerinden kabul edilir.

Özellikle:

- Yapay zekâ desteği; üreteçlerin, sınıflandırıcıların, yeniden düzenlemelerin ve testlerin geliştirilmesini hızlandırır. Yapay zekâ yardımıyla oluşturulan commit'ler, geçmişin denetlenebilir olması için commit mesajlarında bir `Co-Authored-By: Claude` satırı taşır.
- Tüm Star Citizen oyun verisi ayrıştırma mantığı, görev sınıflandırması ve metin işleme kuralları insan proje yürütücüleri tarafından tasarlanır ve gerçek DataForge önbellek örnekleriyle doğrulanır.
- Smart Citizen'ın bazı arayüz ve belge çevirileri, insan çevirileri gelene kadar yer tutucu olarak yapay zekâ tarafından üretilmiştir. Bunlar dil ve metin bazında `languages/TRANSLATIONS.md` dosyasında izlenir ve insan çevirileri geldikçe değiştirilir. Mevcut insan çevirileri yapay zekâ tarafından hiçbir zaman değiştirilmez.
- **Uygulamanın kendisi hiçbir yapay zekâ veya makine öğrenimi özelliği içermez.** Smart Citizen hiçbir model paketlemez, çalışma zamanında hiçbir yapay zekâ hizmetini çağırmaz ve düzenlemelerinizi ya da Star Citizen oyun verilerini bir yapay zekâ sağlayıcısına iletmez.

## Yasal Endişelerin Bildirilmesi

Smart Citizen'ın sahip olduğunuz bir telif hakkını, ticari markayı veya başka bir hakkı ihlal ettiğini düşünüyorsanız — ya da uygulamanın verilerinizi nasıl işlediğine ilişkin bir sorunuz varsa — bir issue açın veya [Osiris DevWorks Discord](https://discord.gg/BNzRegKZ7k) sunucusu üzerinden proje yürütücüleriyle iletişime geçin.
