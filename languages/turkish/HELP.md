# Smart Citizen — Hızlı Başlangıç Kılavuzu

## İlk Kurulum

Smart Citizen açılışta önceki oturumunuzdaki tüm özelleştirmeleri yeniden yükler ve Star Citizen kurulumunuzu denetler — yükleyici bu yolu önceden doldurur, ancak **Yapılandırma** sekmesinden değiştirebilirsiniz. Tüm orijinal yerelleştirme ve DataForge verileri **doğrudan kurulu `Data.p4k` dosyanızdan** alınır (indirme yok, topluluk yansıları yok); bu nedenle kurulumdan sonra ve her oyun yamasının ardından bir kez çıkarma yapmak zorunlu ilk adımdır.

## Basit ve Gelişmiş Mod

Smart Citizen iki moddan birinde açılır ve istediğiniz zaman geçiş yapabilirsiniz.

- **Basit mod** iki düğmeli bir ekrandır: **Geliştirmeleri Uygula** düğmesi tüm zinciri geçerli ayarlarınızla çalıştırır (çıkar, oluştur, uygula; önce oyun dosyanızın yedeği alınır); diğer düğme sizi **Gelişmiş moda** geçirir. Yalnızca geliştirmelerin uygulanmasını istiyorsanız ve metinleri elle düzenlemeniz gerekmiyorsa hızlı yol budur.
- **Gelişmiş mod** uygulamanın tamamıdır: metin tablosu, filtreler, Geliştirmeler sekmesi, Yapılandırma sekmesi ve bu kılavuzdaki diğer her şey.

Varsayılan modunuzu kurulum sırasında seçin veya uygulama içinden istediğiniz zaman geçiş yapın. Basit mod, Gelişmiş modda en son kaydettiğiniz ayarları kullanır.

## 1. Temel Yerelleştirmeyi Data.p4k Dosyasından Çıkarın

**Yapılandırma** sekmesini açın ve **Data.p4k Dosyasından Çıkar** düğmesine tıklayın. Bu işlem orijinal `global.ini` dosyasını ve geliştirme oluşturucunun kullandığı DataForge varlık XML'lerini (gemiler, bileşenler, silahlar, görevler, planlar vb.) açar.

Çıkarma bittiğinde, çıkarılan `base.ini` tabloya otomatik olarak yüklenir — geliştirme dosyalarıyla ve kayıtlı `user.ini` geçersiz kılmalarınızla birleştirilmiş olarak.

## 2. Yerelleştirme Metinlerini Düzenleyin

- Metni düzenlemek için herhangi bir **Özel Değer** hücresine çift tıklayın.
- **Varsayılan Değer** — `Data.p4k` dosyasından çıkarılan `base.ini` içindeki orijinal metin.
- **Geçerli Değer** — geçersiz kılmanızdan önceki etkin değer (temel + içe aktarılan INI katmanları).
- **Özel Değer** — kişisel düzenlemeniz. Her değişiklikte otomatik olarak kaydedilir ve `<veri klasörü>\<kanal>\user.ini` dosyasına yazılır (veri klasörü varsayılan olarak `Documents\Smart Citizen` konumundadır ve her Star Citizen kanalının — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — kendi yalıtılmış geçersiz kılmaları vardır).
- **Durum** sütunu her satırı, geçerli değerinin nereden geldiğine göre etiketler:
  - **Değiştirilmiş** — Özel Değer'i açıkça siz düzenlediniz.
  - **Geliştirilmiş** — geliştirme hattı tarafından otomatik olarak üretildi (istatistik katmanları, plan etiketleri vb.).
  - **Değiştirilmemiş** — `base.ini` içindeki orijinal metin.
  - **Yeni** — anahtar yalnızca geçersiz kılmalarınızda veya geliştirme hattında var; orijinal `base.ini` dosyasında yok.
- **Herhangi bir sütunu yeniden boyutlandırmak** için iki sütun başlığı arasındaki ayırıcıyı sürükleyin veya sütunu en geniş görünür içeriğine oturtmak için ayırıcıya çift tıklayın. Genişlikleriniz açılışlar arasında hatırlanır. Siz kendiniz bir şeyi yeniden boyutlandırana kadar Smart Citizen sütunları pencerenize otomatik olarak sığdırır; böylece yeni bir kurulum kendi ekranında her zaman düzgün açılır. Bu otomatik düzeni geri getirmek için **Pencere Oranlarını Sıfırla** seçeneğini kullanın (aşağıya bakın).

## 3. Önizleme Bölmesi

Sağ üstteki **önizleme bölmesi**, o anda seçili satırın işlenmiş metnini gösterir. Oyunun yerelleştirme metni belirteçleri stillendirilmiş HTML'ye çevrilir; böylece metninizin oyun içinde yaklaşık nasıl görüneceğini görürsünüz:

- `\n` → satır sonu
- `<EM3>...</EM3>` → altı çizili bölüm başlığı
- `<EM4>...</EM4>` → kalın mavi satır içi vurgu (genellikle istatistik değerleri)
- `~mission(Name)` → grileştirilmiş `[Name]` yer tutucusu (oyun gerçek değeri çalışma zamanında yerleştirir)

Bölme tüm sekmelerde görünür kalır ve **Metin Düzenleyici**'de en son seçtiğiniz satırı yansıtır — uzun bir görev açıklamasının veya günce kaydının uygulamadan önce nasıl biçimleneceğini denetlemek için kullanışlıdır.

## 4. Kategoriler

Tek bir alana odaklanmak için **Kategori** filtresini kullanın:

- **Gemiler** — Gemi adları ve açıklamaları (`vehicle_Name*`, `vehicle_Desc*`, ayrıca Wikelo/Collector modları).
- **Gemi Öğeleri** — Kalkanlar, güç üniteleri, soğutucular, kuantum sürücüleri, sıçrama sürücüleri, gemi silahları, füzeler, bombalar, taretler.
- **Görevler** — Görev brifingleri, sözleşme metinleri, ödül açıklamaları.
- **Teçhizat** — FPS silahları, zırhlar, kasklar, giysiler, optikler.
- **Emtialar** — Ticaret malları ve üretim malzemeleri.
- **Günce** — Oyun içi günce / Galactapedia tarzı kayıtlar.
- **Diğer** — Geri kalan her şey.

## 5. Arama ve Filtreleme

- Metinleri anahtara veya metin içeriğine göre bulmak için **arama kutusunu** kullanın.
- **Kategori** ve **Durum** (Değiştirilmiş / Geliştirilmiş / Değiştirilmemiş / Yeni) filtreleriyle birleştirin.
- Yalnızca kendi düzenlemelerinize odaklanmak için **Değiştirilmemişleri Gizle** seçeneğini işaretleyin.
- Her başlığın altındaki **sütun filtre kutuları** tabloyu daha da daraltır.
- Bir sütuna göre sıralamak için o sütunun başlığına tıklayın. Favorileri en üste sıralamak için **★** başlığına tıklayın.

## 6. Gemi Favorileri

- Herhangi bir Gemi satırında **★** sütununa tıklayarak onu favori olarak işaretleyin. Yalnızca bir geminin ad satırı favori yapılabilir; aynı geminin açıklama satırının oyun içinde eşdeğer bir davranışı yoktur, bu nedenle orada yıldız ve sıralama sütunları boş kalır.
- Favori gemilerin adının başına yapılandırılabilir bir ön ek eklenir; böylece oyun içi gemi listesinde en üste sıralanırlar.
- Ön ek karakterini **Geliştirmeler** sekmesinden değiştirin (varsayılan: `*`).
- Arama ve Filtreleme satırındaki **Yalnızca Gemi/Araç Adları** seçeneğini işaretleyerek tabloyu yalnızca gemi ve araç adı satırlarına daraltın; gemi açıklamaları ve diğer tüm kategoriler gizlenir. **★ Yalnızca Favoriler** ile birlikte kullanıldığında tam olarak favori yapabileceğiniz satırlara göz atarsınız.

## 7. Değişiklikleri Oyuna Uygulayın

Düzenlemelerinizi oyun kurulumuna yazmak için **Geliştirmeleri Uygula** düğmesine tıklayın. Herhangi bir şeyin üzerine yazılmadan önce mevcut `global.ini` dosyasının zaman damgalı bir yedeği `<veri klasörü>\<kanal>\backups\` içine oluşturulur.

Düğmenin rengi nerede olduğunuzu söyler: **kırmızı**, son uygulamanızdan bu yana bir şeyin değiştiği (bir düzenleme, yeniden oluşturma, dil veya kanal değişikliği) ve oyunun bunu henüz almadığı anlamına gelir; **yeşil**, oyunun yüklü olanla zaten eşleştiği anlamına gelir ve yeniden yapılacak bir şey olmadığından düğme devre dışı kalır. Aynı kırmızı/yeşil kuralı Geliştirmeler sekmesindeki **Geliştirmeleri Oluştur** ve **Etiket Değişikliklerini Kaydet** düğmeleri için de geçerlidir. Uygula düğmesi hâlâ kırmızıyken uygulamayı kapatırsanız Smart Citizen şimdi uygulamak mı yoksa uygulamadan çıkmak mı istediğinizi sorar; böylece uygulanmamış çalışmanız sessizce kaybolmaz.

Smart Citizen ayrıca başlatıcı sürüm metnine (`Frontend_PU_Version`) küçük bir filigran ekler ve kendi satırında `\nLocalizations Enhanced with Smart Citizen v{VERSION}` yazar. Yerelleştirme paketinizin etkin olduğunu oyun içinde böyle doğrulayabilirsiniz — Star Citizen ana menüsündeki sürüm etiketine bakın. Damga her uygulamada yeniden yazılır; bu nedenle sürümler arasında birikmez.

## 8. Bir Yedeği Geri Yükleyin

Önceki bir sürüme dönmek için araç çubuğundaki **Daha Fazla** menüsünü açın ve **Yedeği Geri Yükle** seçeneğini seçin. Smart Citizen en fazla **5 otomatik yedek** saklar — yenileri oluşturuldukça en eskisi silinir.

## 9. Yerelleştirmeyi Temizleyin

Özel `global.ini` dosyasını oyun dizininden silmek ve oyunu varsayılan (orijinal) metnine döndürmek için **Daha Fazla** menüsünü açın ve **Yerelleştirmeyi Temizle** seçeneğini seçin. `<veri klasörü>\<kanal>\user.ini` içindeki kayıtlı geçersiz kılmalarınıza dokunulmaz ve istediğiniz zaman yeniden uygulanabilir.

## 10. INI İçe Aktarın

Mevcut bir INI dosyasını geçersiz kılmalarınıza katmak için **Yapılandırma** sekmesindeki **INI İçe Aktar...** düğmesini kullanın (araç çubuğunun **Daha Fazla** menüsünde de bulunur). Bir çakışma çözüm iletişim kutusu her anahtar için **Mevcudu Koru**, **İçe Aktarılanı Kullan**, **İçe Aktarılanı Sona Ekle**, **İçe Aktarılanı Başa Ekle** veya **Özel...** bir değer girme seçeneklerinden birini seçmenizi sağlar.

## 11. Yerelleştirme Paketini Dışa Aktarın

**Daha Fazla** menüsünü açın ve **INI Dışa Aktar…** seçeneğini seçerek o anda uygulanmış `global.ini` dosyasını tek bir zip'te toplayın — `SmartCitizen-LocPack-{channel}-{YYYYMMDD}.zip` — başka herkes bunu kendi `StarCitizen\<channel>\data\Localization\english\` klasörüne bırakarak Smart Citizen'ı kurmadan aynı yerelleştirme paketini çalıştırabilir. Ön ayarlarınızı arkadaşlarınızla veya organizasyonunuzla paylaşmak için kullanışlıdır.

## 12. user.ini Dosyasını Sıfırlayın

Etkin kanal için tüm kişisel düzenlemelerinizi silmek üzere **Yapılandırma** sekmesindeki **user.ini Dosyasını Sıfırla...** düğmesini kullanın. Bir onay istemi bunun yanlışlıkla tıklanmadığından emin olur ve önce mevcut `user.ini` dosyasının otomatik bir yedeği `<veri klasörü>\<kanal>\backups\` içine alınır — böylece fikrinizi değiştirirseniz sıfırlama geri alınabilir.

## 13. Ayarları Dışa / İçe Aktarın

Tüm Smart Citizen kurulumunuzu bilgisayarlar arasında taşımak veya temiz bir kurulumdan önce yedeklemek için **Yapılandırma** sekmesindeki **Ayarları Dışa Aktar...** ve **Ayarları İçe Aktar...** düğmelerini kullanın. Dışa aktarma, uygulama ayarlarınızı ve her kanalın `user.ini` geçersiz kılmalarını, Star Citizen kurulum yolunuz dahil, tek bir küçük zip'te toplar; başka bir bilgisayarda anlam taşımayacak makineye özgü yollar ve düzen (veri klasörünüz, önbellek konumu, pencere geometrisi, Metin Düzenleyici sütun genişlikleri) dışarıda bırakılır. İçe aktarma bu yedeği mevcut ayarlarınızın üzerine katmanlar ve içerdiği kanallar için `user.ini` dosyasını değiştirir — mevcut `user.ini` dosyalarınızın anlık görüntüsü önce **user.ini Dosyasını Geri Yükle...** aracılığıyla alınır; bu nedenle içe aktarma geri alınabilir. Star Citizen yolunuz yalnızca içe aktardığınız bilgisayarda hâlâ mevcutsa korunur; aksi halde Smart Citizen bunun yerine yolu otomatik olarak algılar. Smart Citizen, yeni ayarları yüklemek için içe aktarmadan sonra yeniden başlar ve ardından geliştirmelerinizi yeniden oluşturup uygulamayı önerir.

## 14. Oyun Güncellemelerinden Sonra

Star Citizen güncellendiğinde düzenlemeleriniz `<veri klasörü>\<kanal>\user.ini` içinde korunur. Yamalanmış oyundan güncel orijinal metinleri almak için **Data.p4k Dosyasından Çıkar** işlemini yeniden çalıştırın — tablo otomatik olarak yeniden yüklenir ve özelleştirmeleriniz üzerine yeniden uygulanır.

## 15. Dil Değiştirin

**Yapılandırma** sekmesindeki **Dil** açılır listesinden (Kanal'ın yanında) bir dil seçin. Geçiş yapmak hem uygulamanın arayüzünü hem de tablodaki oyun metinlerini değiştirir:

- **İngilizce** (varsayılan), kendi `Data.p4k` dosyanızdan çıkarılan orijinal metinleri kullanır.
- **Diğer diller**, o dilin topluluk tarafından çevrilmiş `global.ini` dosyasını indirir ve İngilizce temelin üzerine katmanlar; böylece çevirinin kapsamadığı her metin kaybolmak yerine İngilizceye döner. İndirme dil başına önbelleğe alınır; daha sonra geri geçtiğinizde önbellek yeniden kullanılır.
- **Geliştirmeler İngilizce kalır.** İstatistik blokları, etiketler ve görev ayrıntıları oyun verilerinden üretilir ve çevrilmiş düzyazının üzerinde İngilizce biçimlerini korur. Karışık bir satır (örneğin İngilizce bir istatistik bloğu içinde Türkçe bir rol adı) beklenen bir durumdur, hata değildir.
- **Dil Dosyası Eşle** (Yapılandırma sekmesi), bir dili farklı bir `global.ini` URL'sine yönlendirmenizi sağlar; örneğin bir topluluk çevirisinin kendi çatalınıza. URL'niz paketle gelen varsayılana göre önceliklidir.
- Bazı arayüz metinleri yalnızca uygulama yeniden başlatıldıktan sonra güncellenir. Tablo metinleri hemen yeniden yüklenir.

Uygulama, oyun kurulumunuzdaki eşleşen dil klasörüne yazar ve `user.cfg` içindeki `g_language` değerini ayarlar; böylece oyun doğru dosyayı yükler.

Çeviriye yardım etmek ister misiniz? Dil başına çeviri durumu depodaki `languages/TRANSLATIONS.md` dosyasında izlenir ve bir makinenin sözcükleri yerine sizinkileri yayınlamayı çok daha fazla isteriz. Discord üzerinden bize ulaşın.

## 16. Uygulama Güncellemeleri

Smart Citizen her başlatıldığında yeni bir sürüm olup olmadığını denetler. Yeni bir sürüm varsa sürüm notları kaydırılabilir bir pencerede iki seçenekle görünür:

- **Şimdi Güncelle** yeni yükleyiciyi indirir, Windows izin ister ve Smart Citizen kapanır, güncellenir ve yeni sürümde yeniden açılır. Düzenlemelerinize, yedeklerinize ve ayarlarınıza dokunulmaz.
- **Daha Sonra** sizi mevcut sürümde tutar; bir sonraki açılışta yeniden sorulur.

Yapılandırma sekmesindeki **Güncellemeleri Denetle** düğmesiyle istediğiniz zaman elle de denetleyebilirsiniz. Taşınabilir sürümler, çalıştırılacak bir yükleyici olmadığından bunun yerine bir **Sürüm Sayfasını Aç** düğmesi gösterir: yeni zip'i indirin ve eski klasörün üzerine açın.

## Geliştirmeler Sekmesi

- Açıklamalara sayısal istatistikler ekleyen istatistik katmanlarını açıp kapatın — SCM hızı, kalkan HP'si, DPS, kargo kapasitesi, madencilik lazeri ışın istatistikleri (Fracture / Extraction), el tipi hurda toplama aracı oranları, plan havuzları, görev XP'si ve daha fazlası. Görev XP'si beslediği itibar yolunu da belirtir (ör. `750 XP (Hauling)`), Battaglia tarama/madencilik sözleşmeleri hedef cevherin temel kaynak imzasını içeren bir `[RS ####]` etiketi taşır ve Madencilik Derlemesi güncesi her cevherin temel RS değerini madencilik konumlarının yanında listeler.
- **Tıbbi Sarf Malzemeleri** — temel CureLife kalemlerine (MedPen, OxyPen, AdrenaPen ve benzerleri) sade dilde bir etki satırı ekler; böylece açıklama yalnızca hikâyesini değil kalemin gerçekte ne yaptığını da söyler.
- **İstatistikleri açıklamanın üstünde göster** — istatistik bloğunu açıklamanın altı yerine üstüne yerleştirir; böylece oyun içinde ilk okuduğunuz şey sayılar olur.
- **Cevher adlarının yanında Kaynak İmzalarını (RS) göster** — çıkarılabilir her cevherin temel Kaynak İmzasını kendi görünen adının sonuna ekler (ör. "Aluminium (RS 4285)"); böylece görev takipçisi dahil oyunun bu adı gösterdiği her yerde görünür. Aşağıdaki Görev Ayrıntıları alanları altındaki Kaynak İmzaları satırından bağımsızdır.
- Her geliştirme kategorisini bağımsız olarak etkinleştirin veya devre dışı bırakın.
- Gemi favorileri ön ek karakterini yapılandırın.
- **Plan sahipliği** kendi **Plan Takipçisi** sekmesine taşındı; sonraki bölüme bakın.
- **Etiket Oluşturucu** — bileşen, füze, gemi silahı ve emtia adlarına yerleştirilen köşeli parantezli etiketleri özelleştirin. Öğeleri ▲/▼ ile yeniden sıralayın, tek tek öğeleri kapatın, kısaltma uzunluğunu değiştirin (`M` / `MIL` / `Military`), ayırıcı (yok, tire, boşluk vb.) ve parantez (köşeli, yuvarlak, yok vb.) seçin ve etiketin adın önünde mi yoksa arkasında mı görüneceğini belirleyin. Bileşenlerin ayrıca isteğe bağlı bir **Tür** öğesi vardır (Kalkan, Soğutucu, Güç Ünitesi vb.) — varsayılan olarak devre dışıdır. Emtiaların **Etiket**, **Kullanım** (bir emtianın üretim malzemelerinin neyi beslediği) ve **Koleksiyon** öğeleri vardır; tümü varsayılan olarak devre dışıdır, istediklerinizi Etiket Oluşturucu'dan etkinleştirin. Kaydedip yeniden oluşturmak için **Etiket Değişikliklerini Kaydet** düğmesine tıklayın. (**Geliştirmeleri Oluştur** da önce bekleyen etiket düzenlemelerini kaydeder; böylece kaydedilmemiş bir değişiklik yeniden oluşturmada kaybolmaz.)
- **Görev Başlıkları** (Etiket Oluşturucu sekmesi) — nakliye görevi başlıklarını rotalarıyla başlatın. Yerleşimi (Başa Ekle, Sona Ekle veya başlığı Değiştir), rota okunu (`>`, `->`, `to` veya her taraftaki tek-veya-çok uç noktayı gösteren şekil kodlu `->-`/`->=`/`=>-`/`=>=`), başlık ayırıcısını ve konumun ne kadarının gösterileceğini (varsayılan olarak tam adres; kısa ad nadir görevlerde görüntülenemeyebilir) canlı önizlemeyle seçin. Bir nakliye seferi `Area18 > Lorville - <orijinal başlık>` gibi okunur; böylece işi sözleşme listesinde bir bakışta görürsünüz ve çok duraklı nakliyeler teslimat noktalarını listeler (`Area18 > Lorville, New Babbage`). Birbirinden bağımsız iki anahtar orijinal başlığı kısaltır: **Orijinal başlıkları kısalt** seçilmiş ifade kısaltmalarını uygular (ör. "Opportunity for Independent Cargo Hauler" → "Intro", "Local Shipment Route" → "Route", ayrıca Ling Family ve rütbe ön eki işleme) ve **Kargo boyutlarını kısalt** kargo boyutu sözcüklerini kısaltır ("Extra Small" → "XS"). Tek tek onay kutuları daha ince denetim sağlar — "Cargo" veya "Haul" sözcüğünü tümüyle kaldırın, "Rank" sözcüğünü çıkarın veya vurgu için "Direct" nakliyelerinin altını çizin — böylece rota ve etiketler uzun başlıklara bile sığar. Aynı sayfadaki **Genel Etiketler** onay kutuları yalnızca başlıkta bulunan etiketleri gösterir veya gizler: itibar ödülü, plan etiketi, `[ACE]`, Battaglia `[RS ####]` etiketi ve itibar yolu adı. Plan etiketi, bir görevin her sürümü plan ödülü veriyorsa `[BP]`, kesin değilse (yalnızca bazı sürümler plan içeriyorsa veya oyun verisi ödülü şans atışı olarak işaretliyorsa) `[BP?]` olarak okunur.
- **Görev Etiketleri** — görev geliştirme bloklarında kullanılan bölüm başlıklarını (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), belirli bir itibar rütbesi olmayan görevlerde gösterilen XP etiketini (varsayılan "Rep") ve başlıklar için kullanılan vurgu etiketini (EM3 = altı çizili, EM4 = renk) özelleştirin.
- **Görev ayrıntı alanları** — MISSION DETAILS bloğunun her satırını tek tek gösterin veya gizleyin (görev türü, zorluk, düşmanlar, itibar, planlar, as pilot ve kaynak imzaları); böylece görev açıklamalarınız yalnızca önemsediğiniz verileri taşır. **Kaynak İmzaları**, Recco Battaglia tarama/madencilik sözleşmelerine hedeflenen her cevherin tam RS değer ilerlemesini listeleyen bir döküm ekler; görev başlığındaki `[RS ####]` etiketinden ve yukarıdaki cevher adı açıklamasından ayrıdır.
- `Data.p4k` dosyasından DataForge verilerini çıkarmak ve geliştirme INI dosyalarını yeniden oluşturmak için **Geliştirmeleri Oluştur** düğmesine tıklayın. `patches/` altındaki bildirimsel yamalar her yeniden oluşturmada eş güçlü olarak yeniden uygulanır; böylece bilinen CIG veri hataları bir oyun yaması beklenmeden düzeltilmiş kalır.

## Plan Takipçisi Sekmesi

Hangi üretim planlarına zaten sahip olduğunuzu takip edin ve bunun oyun içine yansıdığını görün: sahip olunan öğeler görevlerin POTENTIAL BLUEPRINTS listelerinde mavi bir `[Owned]` etiketi alır; böylece bir sözleşme listesi hâlâ neyin peşine düşmeniz gerektiğini bir bakışta söyler.

- **İki liste, tek aktarım.** Mevcut planlar solda, sahip olduklarınız sağda. Öğeleri seçin ve ok düğmeleriyle taşıyın. Sahip olunan liste yeniden başlatmalar arasında korunur.
- **Aradığınızı hızla bulun.** Bir arama kutusu her iki listeyi daraltır ve **Görev / Tür / Sınıf / Boyut / Derece** filtreleri mevcut listeyi bir planın nereden düştüğüne ve ne tür bir öğe olduğuna (Zırh, Mühimmat, FPS Silahı, Gemi Öğesi vb.) göre kısaltır.
- **Herhangi bir planın üzerine gelin** ve türünü, sınıfını, boyutunu ve derecesini, ayrıca onu düşürebilen her görevi satır satır listelenmiş olarak görün.
- **Sahip Olunan Planlar için Günlükleri Tara** sahip olunan listeyi otomatik olarak doldurur: Star Citizen günlük dosyalarınızı oyun içinde aldığınız planlar için okur ve onları sahip olunan olarak işaretler. Yalnızca son taramanızdan sonra alınan planlar içe aktarılır; bu nedenle istediğiniz zaman yeniden çalıştırmak ucuzdur. Tarama, Yapılandırma sekmesinde Star Citizen kurulum yolunuzun ayarlanmış olmasını gerektirir.
- **LIVE/HOTFIX'i de tara (hangisi etkin değilse)** bu iki kanaldan geçerli kanalınız olmayanı da denetler, çünkü aynı hesap ilerlemesini paylaşırlar — LIVE'da kazanılan bir plan HOTFIX günlüklerinde de görünür ve tersi de geçerlidir. Varsayılan olarak etkindir. PTU, EPTU ve TECH-PREVIEW kendi ilerlemelerine sahip ayrı test sürümleridir ve bu anahtardan bağımsız olarak hiçbir zaman taranmaz.
- **Tüm günlükleri yeniden tara (son taramayı yok say)** bir sonraki taramayı, yalnızca son taramanızdan bu yana yeni olanlar yerine her günlük kaydını baştan yeniden okumaya zorlar. Sahip olunan listeniz yanlış görünüyorsa ve normal bir tarama bunu düzeltmiyorsa kullanın. Tarama bittiğinde işareti kendiliğinden kalkar.
- **Sahip Olunan Planları Dışa Aktar… / Sahip Olunan Planları İçe Aktar…** sahip olunan listenizi bilgisayarlar arasında taşır veya bir arkadaşınızla paylaşmanızı sağlar. Dışa aktarma sahip olduğunuz her şeyi bir JSON veya CSV dosyasına yazar; içe aktarma böyle bir dosyayı okur ve bulduklarını ekler, zaten sahip olduğunuz hiçbir şeyi kaldırmaz. scmdb.net dışa aktarımları da içe aktarılabilir. İçe aktarma özeti kaç planın yeni olduğunu söyler ve dosyadaki Smart Citizen'ın takip etmediği adları listeler.
- **Sahip Olunan Etiketlerini Uygula** sahip olunan listeyi değiştirdikten sonra `[Owned]` etiketlerini yüklü metinlerinize yeniden işler. Diğer işlem düğmeleri gibi, sahip olunan listenizde tablonun henüz almadığı değişiklikler varsa **kırmızı**, her şey eşleştiğinde **yeşil** olur.
- Metin tablosunun **Sahip Olunan** sütunu hâlâ bir yıldız gösterir ve sahip olunanları önce sıralar, ancak artık salt okunurdur; sahiplik bu sekmeden yönetilir.

## Yapılandırma Sekmesi

- **Görünüm** — uygulama temasını seçin (aşağıya bakın).
- **Star Citizen Kurulum** — LIVE dizininizin yolu; kurulum sırasında otomatik algılanır, buradan düzenlenebilir. **Kanal** açılır listesi uygulamanın hangi kanalı okuyup yazacağını seçer; **Dil** açılır listesi ise uygulama ve oyun metinlerini değiştirir (yukarıdaki *Dil Değiştirin* bölümüne bakın).
- **Smart Citizen Verileri** — `user.ini`, önbellekler, DataForge çıkarımı, oluşturulan geliştirme INI dosyaları ve yedekler için klasör. Varsayılan olarak `Documents\Smart Citizen`; çıkarma veya önbellek temizliği yavaşsa OneDrive dışına taşıyın.
- **Temel Yerelleştirme (P4K Çıkarma)** — orijinal yerelleştirmeyi ve DataForge varlık verilerini doğrudan kurulu oyununuzdan açmak için **Data.p4k Dosyasından Çıkar** düğmesine tıklayın. Temel metinler ve geliştirme verileri için tek kaynak budur.
- **INI İçe Aktar...** — mevcut bir INI dosyasını çakışma çözüm iletişim kutusu aracılığıyla geçersiz kılmalarınıza katın.
- **user.ini Dosyasını Sıfırla...** — etkin kanal için tüm kişisel düzenlemelerinizi silin. Onay ister ve temizlemeden önce mevcut `user.ini` dosyasını otomatik olarak yedekler.
- **user.ini Dosyasını Geri Yükle...** — kişisel düzenlemelerinizi önceki bir anlık görüntüye geri alın. Smart Citizen `user.ini` dosyasının dönüşümlü yedeklerini saklar (en fazla 5; her değişiklikten önce otomatik olarak alınır); böylece bir içe aktarma veya düzenleme ters giderse önceki bir sürümü seçip metinlerinizi geri alabilirsiniz. Geri yüklemenin kendisi de geri alınabilir: önce mevcut dosyanın anlık görüntüsü alınır.
- **Ayarları Dışa Aktar... / Ayarları İçe Aktar...** — tüm kurulumunuzu (ayarlar ve her kanalın `user.ini` dosyası) tek bir küçük zip'e yedekleyin veya yeni bir bilgisayarda geri yükleyin. Yukarıdaki *Ayarları Dışa / İçe Aktarın* bölümüne bakın.

## Günlük Sekmesi

- Gerçek zamanlı uygulama günlüğü.
- Günlük düzeyine göre filtreleyin, en son kayıtlara otomatik kaydırın ve sorun giderme veya hata bildirimi için günlüğü **Dosyaya aktar…** ile dışa aktarın.

## Temalar

**Yapılandırma sekmesi → Görünüm** bölümünden bir tema seçin:

- **Varsayılan** — SCLE, Star Citizen'ın mobiGlas arayüzünden esinlenen koyu lacivert siber tema.
- **Açık / Koyu** — klasik arayüz temaları.
- **ODW** — Osiris DevWorks imzası, antika altın tonlarıyla lacivert kömür grisi.

## Pencere Düzeni

Smart Citizen pencere boyutunuzu, yana yerleştirilmiş Metin Düzenleyici'nin düzenini ve Metin Düzenleyici sütun genişliklerinizi açılışlar arasında hatırlar. Her sekme kendi içeriğini kaydırır; bu nedenle pencereyi istediğiniz kadar küçültebilir ve denetimlerin sıkışması veya kırpılması yerine kaydırarak her şeye ulaşabilirsiniz.

Düzeniniz kullanışsız bir hâle gelirse — ince bir şerit hâline sürüklenmiş bir sütun veya ekranınıza artık uymayan bir pencere boyutu — **Daha Fazla → Pencere Oranlarını Sıfırla** seçeneğini kullanın. Pencere boyutunu, panel düzenini ve sütun genişliklerini varsayılanlarına döndürür. Ayarlarınıza, düzenlemelerinize ve yerelleştirme verilerinize dokunulmaz.

## Durum Çubuğu

Yüklenen / değiştirilen kayıt sayısını ve çalışan arka plan işlemlerinin (çıkarma, oluşturma, uygulama) durumunu gösterir.

## Rehberli Tur

Rehberli turu yeniden izlemek için istediğiniz zaman araç çubuğundaki **Rehberli Tur** düğmesine tıklayın — her denetimi işaret eden ekran üstü açıklamalarla temel iş akışının adım adım anlatımı. Tur, yeni bir sürümü ilk kez başlattığınızda da otomatik olarak çalışır; böylece yeni bir kurulum hiçbir zaman boşlukta kalmaz. Kapatmak için istediğiniz zaman **Atla** düğmesine basın.

## SSS Sekmesi

**SSS** sekmesi en sık aldığımız soruları doğrudan uygulama içinde yanıtlar — Smart Citizen'ın hangi dosyalara dokunduğu, kullandığınız için yasaklanıp yasaklanamayacağınız, Windows'un yükleyiciyi neden işaretlediği ve değişikliklerinizi nasıl geri alacağınız. Önce oraya bakın; sorunuz orada yoksa Discord bir tık uzağınızda.

## Klavye Kısayolları

- **Ctrl+Shift+C** — Filtrelenmiş satırları panoya kopyalar (anahtar=değer biçiminde).

## Sorun Giderme

- **Tabloda hiçbir şey yok** — **Data.p4k Dosyasından Çıkar** işleminin tamamlandığından ve çıkarma sonrası yeniden yüklemenin bittiğinden emin olun, ardından ayrıştırma hataları için **Günlük Sekmesi**'ne bakın.
- **Geliştirmeler boş veya öğeler eksik** — Geliştirmeler sekmesinden **Geliştirmeleri Oluştur** işlemini çalıştırın; bir DataForge önbelleği gerektirir (henüz yapmadıysanız önce **Data.p4k Dosyasından Çıkar** düğmesine tıklayın).
- **Geliştirmeleri Uygula başarısız oluyor** — **Yapılandırma Sekmesi**'ndeki Star Citizen kurulum yolunu ve oyunun çalışmadığını doğrulayın.
- **Çıkarma, Data.p4k dosyasının kilitli olduğunu söylüyor** — RSI Launcher bir güncelleme indiriyor veya doğruluyor. Bitmesini bekleyin (veya başlatıcıyı kapatın), ardından **Data.p4k Dosyasından Çıkar** düğmesine yeniden tıklayın.
- **Oyun güncellemesinden sonra eski veriler** — **Data.p4k Dosyasından Çıkar** işlemini yeniden çalıştırın, ardından geliştirmeleri yeniden oluşturun.

## Bilinen Sorunlar

Bazı görev metni anormallikleri Star Citizen'ın kendi verilerinden kaynaklanır — bir sözleşme kaydındaki yanlış bir yerelleştirme anahtarı başvurusu veya verisi gerçek bir görünen ada bağlanmayan bir plan ödülü. Oyun sözleşmeleri ve plan ödüllerini çalışma zamanında kendi `Data.p4k` dosyasından okur; bu nedenle Smart Citizen bunları kaynağında düzeltemez, yalnızca ürettiği ve uyguladığı *metni* düzeltebilir. Uygulanabilir olduğunda bunları veri veya oluşturma düzeyinde aşarız; böylece oyun içi sonuç yine de doğru okunur.

- **Jorrit Dossier — "Updated Power Usage Data" Energy Anomaly metnini gösteriyor** — CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). CIG'nin `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` sözleşmesi, `Description` parametresini kendi `P2M4_Repeat_desc` yerine `@Hockrow_FacilityDelve_P2M1_Repeat_desc` anahtarına yönlendirir; bu nedenle oyuncular oyun içinde "Power Usage Data" başlıklı bir görev için P2M1'in Energy Anomaly hikâye metnini görür. Smart Citizen bunu, her ikisi de `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json` dosyasında bildirilen iki adımla aşar:
  1. Geliştirme oluşturucumuzun doğru P2M4 plan havuzunu (Corbel Smolder, Geist Rogue/Whiteout) P2M1'inkine katlamak yerine `P2M4_Repeat_desc` anahtarına bağlaması için bir DataForge XML düzenlemesi.
  2. `P2M4_Repeat_desc` anahtarının tüm içeriğini (hikâye metni ve kendi plan havuzu) etiketli bir ayırıcıyla `P2M1_Repeat_desc` anahtarının sonuna ekleyen bir yerelleştirme metni geçici çözümü. Oyun hatalı işaretçiyi okuyup her iki sözleşme için de `P2M1_Repeat_desc` anahtarına baktığından, P2M4 sözleşmesi artık amaçlanan içeriğini gösterir. P2M1 oyuncuları P2M4 bloğunu kendi açıklamalarının ardından etiketli bir ek olarak görür — daha kalabalık, ama artık her iki sözleşme de doğru plan havuzunu ve doğru hikâye metnini gösterir.

  CIG STARC-176797 sorununu düzelttiğinde yama dosyasının tamamı silinebilir ve bir sonraki yeniden oluşturma yine temiz, ayrı açıklamalar üretir.

- **Yakıt ikmali görevleri bozuk nozul adları gösteriyor** (ör. bir görevin POTENTIAL BLUEPRINTS listesinde "Norfield" yerine "Nozzle Fuelgiver Grin Nozzlefast"). Yakıt nozulu plan ödülleri, CIG'nin verilerinde diğer üretilebilir öğeler gibi çözümlenebilir bir varlık adına bağlanmaz; bu nedenle geliştirme oluşturucumuz gerçek ürün adı yerine dahili dosya adının çözülmüş bir sürümüne düşüyordu. Bilinen 8 yakıt nozulu varyantının tümü (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s) için `scripts/generate_enhancements_ini.py` içindeki bilinen ad düzeltmesiyle giderildi; zaten gördüğünüz görevlerde düzeltmeyi almak için **Geliştirmeleri Oluştur** ve **Geliştirmeleri Uygula** işlemlerini yeniden çalıştırın.

## Geri Bildirim, Hatalar ve Özellik Oylaması

- Özel Smart Citizen Discord kanalında **hata bildirin, özel yapılandırmalarınızı paylaşın ve gelecek özelliklere oy verin**: [Osiris DevWorks Discord — #smart-citizen feedback & voting](https://discord.com/channels/1438175448420057323/1472394204347895890) (önce Osiris DevWorks Discord sunucusuna katılmayı gerektirir — [davet](https://discord.gg/BNzRegKZ7k)). Özellik önceliklendirmesi o kanaldaki tepkiler/oylarla belirlenir; bir istek ne kadar çok talep görürse o kadar erken gelir.
- Bir hata bildirirken günlüğü ekleyin (Günlük Sekmesi → **Dosyaya aktar…**) ve kullandığınız Star Citizen sürümünü belirtin; böylece orijinal sorunları yukarı akış değişikliklerinden ayırt edebiliriz.
