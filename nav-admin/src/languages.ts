export type Language = {
  code: string
  native: string
  english: string
  aliases: string[]
}

export const PROMOTED_LOCALES = ['en', 'fr', 'es', 'zh', 'pa'] as const

// 22 core + ~90 additional from the model card. Codes are ISO 639-1
// where available, FLORES-200 3-letter otherwise. Dialect variants
// of Arabic (Egyptian, Moroccan, Levantine) collapse to `ar` — the
// kiosk doesn't need to distinguish; the prompt can later.
const RAW: [string, string, string, string?][] = [
  // ── Promoted (Vancouver BC context) ─────────────────
  ['en',  'English',      'English',      'eng'],
  ['fr',  'Français',     'French',       'francais'],
  ['zh',  '中文',          'Chinese',      'mandarin cantonese 简体中文 繁體中文 普通话'],
  ['pa',  'ਪੰਜਾਬੀ',       'Punjabi',      'gurmukhi shahmukhi panjabi'],
  ['es',  'Español',      'Spanish',      'espanol castellano'],

  // ── Core 22 ──────────────────────────────────────────
  ['de',  'Deutsch',      'German',       ''],
  ['ja',  '日本語',        'Japanese',     ''],
  ['ko',  '한국어',         'Korean',       ''],
  ['pt',  'Português',    'Portuguese',   'portugues'],
  ['ru',  'Русский',      'Russian',      ''],
  ['ar',  'العربية',      'Arabic',       'العربي fusha'],
  ['it',  'Italiano',     'Italian',      ''],
  ['nl',  'Nederlands',   'Dutch',        ''],
  ['pl',  'Polski',       'Polish',       ''],
  ['ro',  'Română',       'Romanian',     ''],
  ['sv',  'Svenska',      'Swedish',      ''],
  ['tr',  'Türkçe',       'Turkish',      ''],
  ['hi',  'हिन्दी',         'Hindi',        ''],
  ['vi',  'Tiếng Việt',   'Vietnamese',   ''],
  ['th',  'ไทย',          'Thai',         ''],
  ['id',  'Bahasa Indonesia', 'Indonesian', ''],
  ['ms',  'Bahasa Melayu','Malay',        ''],
  ['fil', 'Filipino',     'Filipino',     'tagalog tl'],

  // ── Additional — Europe ──────────────────────────────
  ['uk',  'Українська',   'Ukrainian',    ''],
  ['fa',  'فارسی',        'Persian',      'farsi parsi'],
  ['cs',  'Čeština',      'Czech',        ''],
  ['el',  'Ελληνικά',     'Greek',        ''],
  ['da',  'Dansk',        'Danish',       ''],
  ['hu',  'Magyar',       'Hungarian',    ''],
  ['fi',  'Suomi',        'Finnish',      ''],
  ['nb',  'Norsk Bokmål', 'Norwegian',    'bokmal no'],
  ['nn',  'Norsk Nynorsk','Nynorsk',      ''],
  ['sk',  'Slovenčina',   'Slovak',       ''],
  ['bg',  'Български',    'Bulgarian',    ''],
  ['bs',  'Bosanski',     'Bosnian',      ''],
  ['ca',  'Català',       'Catalan',      ''],
  ['sq',  'Shqip',        'Albanian',     ''],
  ['lv',  'Latviešu',     'Latvian',      ''],
  ['hr',  'Hrvatski',     'Croatian',     ''],
  ['lt',  'Lietuvių',     'Lithuanian',   ''],
  ['sl',  'Slovenščina',  'Slovenian',    ''],
  ['et',  'Eesti',        'Estonian',     ''],
  ['mk',  'Македонски',   'Macedonian',   ''],
  ['sr',  'Српски',       'Serbian',      ''],
  ['is',  'Íslenska',     'Icelandic',    ''],
  ['gl',  'Galego',       'Galician',     ''],
  ['be',  'Беларуская',   'Belarusian',   ''],
  ['af',  'Afrikaans',    'Afrikaans',    ''],
  ['hy',  'Հայերեն',      'Armenian',     ''],
  ['eu',  'Euskara',      'Basque',       ''],
  ['la',  'Latina',       'Latin',        ''],
  ['cy',  'Cymraeg',      'Welsh',        ''],
  ['ga',  'Gaeilge',      'Irish',        ''],
  ['mt',  'Malti',        'Maltese',      ''],
  ['lb',  'Lëtzebuergesch','Luxembourgish',''],
  ['fy',  'Frysk',        'Frisian',      ''],
  ['fo',  'Føroyskt',     'Faroese',      ''],
  ['gd',  'Gàidhlig',     'Scottish Gaelic', ''],
  ['co',  'Corsu',        'Corsican',     ''],
  ['oc',  'Occitan',      'Occitan',      ''],
  ['se',  'Davvisámegiella','Northern Sami',''],
  ['rm',  'Rumantsch',    'Romansh',      ''],
  ['gsw', 'Schwyzerdütsch','Swiss German',''],
  ['nds', 'Plattdüütsch', 'Low German',   ''],

  // ── Additional — South Asia ──────────────────────────
  ['bn',  'বাংলা',         'Bengali',      'bangla'],
  ['ur',  'اردو',          'Urdu',         ''],
  ['mr',  'मराठी',         'Marathi',      ''],
  ['ta',  'தமிழ்',         'Tamil',        ''],
  ['ne',  'नेपाली',        'Nepali',       ''],
  ['ml',  'മലയാളം',       'Malayalam',    ''],
  ['kn',  'ಕನ್ನಡ',        'Kannada',      ''],
  ['gu',  'ગુજરાતી',       'Gujarati',     ''],
  ['si',  'සිංහල',         'Sinhala',      'sinhalese'],
  ['as',  'অসমীয়া',        'Assamese',     ''],
  ['sd',  'سنڌي',          'Sindhi',       ''],
  ['or',  'ଓଡ଼ିଆ',         'Odia',         'oriya'],
  ['bo',  'བོད་སྐད་',        'Tibetan',      ''],
  ['my',  'မြန်မာ',         'Burmese',      'myanmar'],
  ['km',  'ខ្មែរ',           'Khmer',        'cambodian'],
  ['lo',  'ລາວ',           'Lao',          ''],
  ['dv',  'ދިވެހި',         'Dhivehi',      ''],

  // ── Additional — Central & West Asia ─────────────────
  ['az',  'Azərbaycan',   'Azerbaijani',  ''],
  ['kk',  'Қазақша',     'Kazakh',       ''],
  ['ky',  'Кыргызча',     'Kyrgyz',       ''],
  ['uz',  'Oʻzbekcha',    'Uzbek',        ''],
  ['tk',  'Türkmençe',    'Turkmen',      ''],
  ['tg',  'Тоҷикӣ',       'Tajik',        ''],
  ['mn',  'Монгол',       'Mongolian',    ''],
  ['ka',  'ქართული',      'Georgian',     ''],
  ['ps',  'پښتو',          'Pashto',       ''],
  ['ug',  'ئۇيغۇرچە',     'Uyghur',       ''],
  ['tt',  'Татарча',      'Tatar',        ''],
  ['ba',  'Башҡортса',    'Bashkir',      ''],
  ['cv',  'Чӑвашла',      'Chuvash',      ''],
  ['os',  'Ирон',         'Ossetian',     ''],
  ['sah', 'Саха тыла',    'Yakut',        ''],

  // ── Additional — Africa ──────────────────────────────
  ['am',  'አማርኛ',          'Amharic',      ''],
  ['ti',  'ትግርኛ',          'Tigrinya',     ''],
  ['so',  'Soomaali',     'Somali',       ''],
  ['sw',  'Kiswahili',    'Swahili',      ''],
  ['ha',  'Harshen Hausa','Hausa',        ''],
  ['yo',  'Èdè Yorùbá',   'Yoruba',       ''],
  ['ig',  'Asụsụ Igbo',   'Igbo',         ''],
  ['zu',  'isiZulu',      'Zulu',         ''],
  ['xh',  'isiXhosa',     'Xhosa',        ''],
  ['st',  'Sesotho',      'Sesotho',      ''],
  ['sn',  'chiShona',     'Shona',        ''],
  ['rw',  'Ikinyarwanda', 'Kinyarwanda',  ''],
  ['rn',  'Ikirundi',     'Kirundi',      ''],
  ['ny',  'Chichewa',     'Chichewa',     ''],
  ['mg',  'Malagasy',     'Malagasy',     ''],
  ['om',  'Afaan Oromoo', 'Oromo',        ''],

  // ── Additional — East & Southeast Asia ───────────────
  ['yue', '粵語',          'Cantonese',    'cantonese yue 粤语'],
  ['ceb', 'Bisaya',       'Cebuano',      ''],
  ['jv',  'Basa Jawa',    'Javanese',     ''],
  ['su',  'Basa Sunda',   'Sundanese',    ''],
  ['hil', 'Hiligaynon',   'Hiligaynon',   ''],
  ['mww', 'Hmoob Dawb',   'White Hmong',  'hmong'],
  ['hif', 'Fiji Hindi',   'Fiji Hindi',   ''],

  // ── Pacific & other ──────────────────────────────────
  ['mi',  'Te Reo Māori', 'Māori',        'maori'],
  ['sm',  'Gagana Samoa', 'Samoan',       ''],
  ['haw', 'ʻŌlelo Hawaiʻi','Hawaiian',    ''],
  ['kl',  'Kalaallisut',  'Greenlandic',  ''],
  ['ht',  'Kreyòl Ayisyen','Haitian Creole',''],
  ['pap', 'Papiamentu',   'Papiamento',   ''],
  ['eo',  'Esperanto',    'Esperanto',    ''],
  ['yi',  'ייִדיש',        'Yiddish',      ''],
  ['he',  'עברית',        'Hebrew',       ''],
]

export const LANGUAGES: Language[] = RAW.map(
  ([code, native, english, aliases]) => ({
    code,
    native,
    english,
    aliases: aliases ? aliases.split(' ').filter(Boolean) : [],
  }),
)

export function languageName(code: string): string {
  return LANGUAGES.find(l => l.code === code)?.english ?? code
}

export function languageNative(code: string): string {
  return LANGUAGES.find(l => l.code === code)?.native ?? code
}