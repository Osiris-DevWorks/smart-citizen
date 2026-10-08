"""Reference glyphs for the SCO digit reader (``sco_digit_reader.py``).

Each entry is one digit cut from a real mining-scan readout: ``(digit,
width, height, red-channel pixels as hex, row-major)``. Taken from Amr's
2560x1600 screenshots of a Drake Golem (``g*``) and a MISC Prospector
(``p*``) cockpit, 2026-10-07/08. The reader compares a captured glyph to
every entry here, so adding a sample is how to teach it a new look.
"""

DIGIT_SAMPLES: tuple[tuple[str, int, int, str], ...] = (
    ("7", 6, 10, "caf7f0ecffe4a0abc1b6f1f15e585e6ed5ee4a494482eed9484464b5ffab4a4d89cef5773e5589f0d9584c74a5f2b4424f79c5ff694b4f74b3d05d45"),  # g1
    ("2", 6, 10, "8bc4dfbd9b52fbeef0eeefb4cdaa5a87fef4af7e6580e9ef7783a8a3ffebb3f3f1c0ef99fddd9c7f8e5aefed604f514afff5938c8883dcfdfdeeecd9"),  # g1
    ("0", 6, 10, "5e99b4b38e46b9f9f1f1f2afe3e36878f2f4edff655bdeffeff36163cbffe8ff6d6cc2fbe6ff5a5cb5fdf4fb6270b3ffd3ffa88dd8fe72eef5edefb6"),  # g1
    ("0", 6, 10, "5379968f6a4a93f9fbfeed92b6e76973f6ffc3ff815ac7ffc4fc8967b6ffcaf58871aceec1f78965a8fbc2f28e70b5feadf1a690bcfc82ffeefaf1c9"),  # g1
    ("1", 7, 11, "6bb4c6dfce876b9bf7fdffec9b8ca0afd7f8ff987a87a1c7f8ff9a797898bbecff997a8199bee6ff997c8798c3f7ff9f757f9cc4fffbae7488c2d6fff4d398a3f6f3f5f7fac9babfd0cdd5d8a4"),  # g2
    ("0", 7, 11, "728fc4e6d3af8ea2d4f6fdfcffb7d0e5fad3e5f2fcc5f0feadacfcffc2f6faa2a4faffc2e9f9aeb9f5f7b7e4faadb0f4feb4fafdc4bff1ffb3f5fff1eaf0f89cc0fafdf2edb1a489a6bcd5a281"),  # g2
    ("2", 7, 11, "6e96bee2e7b48e9ee2f9f7f4fffbbaf5ffccc3f2ff84b9d39798f1f4858c94bcc1fcfb7ac7fff4e7f4f3a8f4ffe9d3bca6bafbf8b69f8670b3fdf4d49daaada6f3fcfffefffe9db3c4ddcfeec1"),  # g2
    ("0", 7, 11, "90a5dfd3bb9672d3edf5fbffe1a1faefe6cbfff6bbffe0c892f1fdc6f6f3b682dcf2c7f8fabc95d7f3c1f6f6bb8cdaf8baf5fac593deefbfeceeeecaf0edb3b9e8fff0f8f78c9c93b3c2d88777"),  # g2
    ("0", 7, 11, "7996cadcb58464bdfff2f9ffef9cf8f2fdc4faffc4e6efcd88d0f2c2e6f4b27dc4f8c6ebf4b69ccbfdc9e0eeb69ec3f1c7e1f6c69dc8eac4d7fae9c5e0f2b4a8f0fff6eff59d8c96b0c7d77b71"),  # g2
    ("6", 6, 12, "609edddab766bbffebfbf9b9b1f89776f5faadf39759c2f7a4ffd1c39a52a8eeeaedeab0b5e29c75f2f2a8f6a768edffb4f08861e5f2b7ffd7a6ebff89feeaebf4ef568ababfbf80"),  # p1
    ("8", 6, 12, "5095b18d703be0e9f9e8f774edd9a2d4ffade9f95688f8d6f4f58386feb9cdf8edd8f379c4efe0f0ff73e0d167b5ef92f6f16d8dfebcf6f09ca3f7a9f1ddf0dae96c9ac8e0cbb04d"),  # p1
    ("0", 7, 12, "495e7b905a54475bc5eff6fbc74ab5e5cda9f7ee8394f3ce56adfaf198f8ce608af3ed9fe7d76d9de9e6a8e7e16998f5dfa6ecbe6c8beadfadf4b7649ef4d3acefc479bbe4e286faf5d1eef57767c5f6f4e0de5a"),  # p1
    ("0", 6, 12, "444d707257405ad0ffefffa8bbe8e6c7ffe2abe5936ab4feb6ff71689bedb8f67562b9e9ceea8169b1efb5f9606cbfdec9ee846abde2c0fb7a67c5eeaeebfdb0dbe75cf4f7e9e8d6"),  # p1
    ("2", 6, 12, "3a425256433e4be9fbffe93dd8f8d2fffbd0e0ed7975edfac4fb7577dff362565899ecfb4c3f85c8fb8a3f5cc5edeb483c93e1eb86546dd8f8ba3e4db4f2f3b6b4bfc3e9f8f5ffee"),  # p2
    ("0", 6, 12, "426292914a3fbdffeeffe97ecfd8a1ddfadbe3d4606af5fbfaea6474f5f9f8d34b6cf0f4f7ff675efffce9fb507bf7faedfc5a6ee9fdf5ff7876f1fbc9feedc5ffe780cdf9d5cc69"),  # p2
    ("0", 6, 12, "6eb2dcc67d46fcf3fffef06ee5cf7ac4f2cefef16772f7f5faef6273f9f5f3ff5f82eaf4fcf55f74eff5faf85777f2efeff35e72e3ffe9f4929ce4efbff9f5deeeb96bb7cccbc760"),  # p2
    ("0", 6, 12, "7fe9f8f5ca75f7f3feffff94e1bc63a4ffebf8c75b6ee9eeffc36564ffe9f0d45d75ffe8facf5d6cfaf5fcd36269f5efffdd5c70fff2fffeaa9ceeffa9ecffcefca25f9ab29da445"),  # p2
    ("1", 4, 11, "c3ffffabccecffce7188ffd05983fccb678ff3d3618dffd8727efecd688dffcf6a89ffd96781fad46780ffaf"),  # p3
    ("5", 6, 11, "fef4fefef78ff9d5b1b9f676f7e660635b46fff05e5a4a4af6feeafac25ffcf2e9fbf38ac59465aefaca916d5c8cf3d0fbd47db4f8b9fafddee2f4a78df1e7e3d572"),  # p3
    ("6", 6, 11, "91efffeeff85cdf0c8ddfbecb8fc8c53fefdbdf6a34d6c67cbe7f5fbff88b0f5d4d8ffeabeef8d55f3fac6edad59ecf3b1f3ad65eeff9deefcaaffee6cbaffd5eeab"),  # p3
    ("9", 7, 11, "67e8eef9fcc754b4e6e7b4faec8e98f5ae68c8f5b49bffb44da6ffc08ff0d874b3edc181ffffdedceeb15a9fefdbd3ffc17c888a74b4f6a1b7fcf77bb7fac08bf6f4d3dcf1866698e3e2dbb361"),  # p3
    ("7", 6, 11, "fff2f6f1fae5edd9bcc8e9ff7e7065abedf14d5165caffa84a467adafe51535fa3f7f6464a72baebb73d6080cbff61414e8ad6ef383773a5ffab3a3d779bff654946"),  # p3
    ("8", 6, 11, "9eede5f6c05bc2dfaef1f29acbe94385f3cdf8ef728debbfc3f5cbbbf287a7feecfff359bbd16abef09ee8f54a91ffcdfaf8607fe9c7ddffebc3f48b86f9ebc9cb53"),  # p4
    ("5", 6, 11, "ecfaeef3efffcdf3b6b9c5eea2f987573d48b1ff9049534ab3f0f0f9d18cc1f2fbf1f5f680c98b6bd9f259675d62b6f0e9f5a559aef291fcf8c3d7ff5da9f8e9d2c9"),  # p4
    ("4", 6, 11, "5492fff0484468a5f2e1464676aff18a4a3a7ac7f9614c439bf4bb63ad97baff98abfefae3f0ecaceaf6e2f8f6d5e9fc74776e87e5ff5a574884f1ec4042566de9ed"),  # p4
    ("0", 6, 11, "5fe6fff4dd70c1eec2f2ffcfc2f75c5ae3efcfe95269cfe8c1e94e5bc9ecc2ee5467c5e9c7ee3b6cc4ffcff54c70b9f1c3f25c74c1f1a7f4f5a8efdf84e5f8d7ec95"),  # p4
    ("1", 4, 11, "cfffffc0aae3e5fb6a96f5eb5890eee9708cf5eb7194ebd86697f2d2679bf3d1678af1d6669effd56d8ddaaf"),  # p5
    ("5", 5, 11, "f5ffebf7fff1fcc9cee0f1ce605f4ef1e97c825df9f9fdf4c2fdefccffe587807edaffad756daae8f3d19fcaedf0ffecffec89c4d6c799"),  # p5
    ("6", 6, 11, "a1fff7ffd051ecf7d2fffa91d8e57fb0ecc4e2eca29ac285efffe7f4e44fd7eecdeeffaedef779adf6e6e8ed6da0f7f4f9ff89aff4e7c8ffe0e7ff9883d1e7cdd567"),  # p5
    ("0", 6, 11, "69dcf5fffb9acaf3eceff6fbb0ee986ed8ffa2eea269afffaff3b57db6ebb7f4987daefccaf59082bcffbceaa876b4f2bef3ad86c5ffa2f6f5e0f0eb7bb2ebded594"),  # p5
    ("0", 6, 11, "7fe6fff8d061deffe4f3ffd7bae28192e3fdd3ff857cd7ffdcff8984daffd6fb897fe6fae1fe8c80eff4e5f8838adff7eefc918eedf7c2fffdd5fae189d7e9ebd57b"),  # p5
    ("3", 6, 12, "598a99aead87f1f2f0f8f1f77c8ca0c5fcd2664e8edbe6763b92caf4a4425a91ccfced835a464c8afbf34b555b4eeff5a7cf7752e2ffdcfbd175ddea82e9f7c6f1f551a6ddc0c266"),  # p6
    ("4", 7, 12, "3f9adcc647303e59dbf2d448535262d1ed74493f548be5fb46443850acfba85f9d8841b3e778b5f9eb5ce0ffb88aecf870e4f7e1dff8edbb8dada4a3e7ff815559516ce5ed6038594c6ef8f16b414b5455a4b65e"),  # p6
    ("0", 6, 12, "8ff2ffe9f95cc3dfb7f3fccfd6cb6173effafff9576cf8f9f4f3656af5eaebf85b5de3f6f1ec6464e7eaf7f25760e1f4fdf16b68d8fac7f7f8adede76af6f3d2f6a7437f89958852"),  # p6
    ("0", 6, 12, "a9f0f6f7ee79dcd0a3c8ffb9d4f55273f2e9ffea5b70f3eefbea5366e8ebe7e75465e7fbf1ef596ee1e7ddf55e5fe9ebe6f38563e8f2bcefffbdffde79c2f8c1cf7a56677f716c35"),  # p6
)
