https://arxiv.org/html/2609.40181v2




Here is a precise, step-by-step guide to using Index-Translate efficiently on Ollama. The key is to treat it as a specialized translation engine, not a general chat model—this means configuring it correctly with a custom Modelfile and using its exact prompt format.

### 📥 Step 1: Choose and Pull the Right Model

The first step is selecting a model size and quantization that fits your hardware. The Ollama commands below pull the model directly from Hugging Face.

| Model | Recommended Ollama Pull Command | Approx. VRAM (4-bit) | Best For |
| :--- | :--- | :--- | :--- |
| **Index-Translate-2B** | `ollama run hf.co/IndexTeam/Index-Translate-2B-GGUF:Q4_K_M` | ~2–5 GB | Low-resource environments, fast translation on CPU or small GPUs. |
| **Index-Translate-9B** | `ollama run hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M` | ~6–10 GB (fits on a 16GB GPU) | A strong balance of quality and performance for most kiosk use cases. |
| **Index-Translate-35B-A3B** | `ollama run hf.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF:Q4_K_M` | ~21–36 GB+ | Maximum quality, requiring a high-end GPU or 32GB+ system memory. |

**Note on Quantization**: The `Q4_K_M` variant is generally the "recommended" balance between size and quality. For the 9B model, the `IQ4_XS` variant is also a good, slightly smaller option.

### ⚙️ Step 2: Create a Custom Modelfile for Correct Configuration

You cannot use the model effectively with default settings. You need a `Modelfile` to enforce the correct decoding strategy and to structure the prompt.

1.  Create a file named `Modelfile` (no extension).
2.  Paste the following content into it. This configuration is critical for reliable output.

```dockerfile
FROM hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M

# CRITICAL: Set greedy decoding for deterministic translation.
# The model card explicitly recommends temperature=0.
PARAMETER temperature 0

# CRITICAL: The model expects a specific prompt structure.
# This template wraps your input, but the full prompt (with translation instructions) 
# must be constructed in your application code (see Step 3).
TEMPLATE """{{ .Prompt }}"""

# Set a reasonable context window. Prompt and output both count toward this limit.
PARAMETER num_ctx 4096
```

3.  Build the custom model in Ollama using the `create` command:
    ```bash
    ollama create index-translate-9b -f Modelfile
    ```
    You can now run your properly configured model with `ollama run index-translate-9b`.

### 📝 Step 3: Construct Prompts Using the Official Template

This is the most crucial step for efficiency. The model is trained on a specific **Chinese-language instruction template** and expects it exactly. Sending a plain English command like "Translate this" will yield poor results.

Your application code must build the full prompt string before sending it to Ollama.

**For standard, unconstrained translation**, the template is:

```text
请将以下{source-language}文本翻译为{target-language}，直接输出翻译结果，不要进行任何解释。
{source-text}
```

**How to use it in practice (example for a Python application):**

```python
def build_translation_prompt(source_text, target_lang_name, source_lang_name="中文"):
    # Note: The model card suggests using full language names in Chinese.
    # e.g., "英语" (English), "法语" (French), "西班牙语" (Spanish), "日语" (Japanese), "中文" (Chinese)
    prompt_template = f"请将以下{source_lang_name}文本翻译为{target_lang_name}，直接输出翻译结果，不要进行任何解释。\n{source_text}"
    return prompt_template

# Example: Translate from English to French
text_to_translate = "Hello, how can I help you today?"
prompt = build_translation_prompt(text_to_translate, target_lang_name="法语")
# Now, send 'prompt' as the input to your ollama model.
# The model will return ONLY the French translation.
```

**For constrained translation (advanced)**, such as enforcing a glossary, the model uses a more complex `instTrans` structure with separate sections for hard and soft requirements. The official client code on GitHub provides a full reference for this.

### 🚀 Step 4: Best Practices for Efficient Operation

*   **Always Use `temperature=0`**: This is non-negotiable for consistent, high-quality translation. The Modelfile above handles this.
*   **Disable "Thinking"**: The model has a reasoning mode that must be disabled for translation. The official client does this by setting `enable_thinking: false` in the chat template. If your Ollama version or client doesn't handle this automatically, you may need to strip out `…` tokens from the response, as shown in the official Python example.
*   **Use Chinese Language Names in Prompts**: The client maps short language codes to Chinese names. For optimal results, use the full Chinese name for your target language in the prompt (e.g., `法语` for French, `西班牙语` for Spanish).
*   **Manage Context Length**: Remember that the prompt length, source text, and generated output all count toward the `num_ctx` limit you set. For long documents, you may need to increase this value, but be mindful of memory usage.
*   **Start with the 9B Model**: For a kiosk, the 9B model (quantized to Q4) is often the "sweet spot" for quality versus resource usage, fitting comfortably on a 16GB GPU.

By following these steps—pulling the right model, enforcing `temperature=0` with a custom Modelfile, and using the official Chinese prompt template—you will be using Index-Translate as it was designed, ensuring reliable and high-quality translations for your kiosk.

If you decide to test a specific model size or run into issues with the prompt format, let me know and I can provide more tailored examples.Here is a precise, step-by-step guide to using Index-Translate efficiently on Ollama. The key is to treat it as a specialized translation engine, not a general chat model—this means configuring it correctly with a custom Modelfile and using its exact prompt format.

### 📥 Step 1: Choose and Pull the Right Model

The first step is selecting a model size and quantization that fits your hardware. The Ollama commands below pull the model directly from Hugging Face.

| Model | Recommended Ollama Pull Command | Approx. VRAM (4-bit) | Best For |
| :--- | :--- | :--- | :--- |
| **Index-Translate-2B** | `ollama run hf.co/IndexTeam/Index-Translate-2B-GGUF:Q4_K_M` | ~2–5 GB | Low-resource environments, fast translation on CPU or small GPUs. |
| **Index-Translate-9B** | `ollama run hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M` | ~6–10 GB (fits on a 16GB GPU) | A strong balance of quality and performance for most kiosk use cases. |
| **Index-Translate-35B-A3B** | `ollama run hf.co/IndexTeam/Index-Translate-35B-A3B-preview-GGUF:Q4_K_M` | ~21–36 GB+ | Maximum quality, requiring a high-end GPU or 32GB+ system memory. |

**Note on Quantization**: The `Q4_K_M` variant is generally the "recommended" balance between size and quality. For the 9B model, the `IQ4_XS` variant is also a good, slightly smaller option.

### ⚙️ Step 2: Create a Custom Modelfile for Correct Configuration

You cannot use the model effectively with default settings. You need a `Modelfile` to enforce the correct decoding strategy and to structure the prompt.

1.  Create a file named `Modelfile` (no extension).
2.  Paste the following content into it. This configuration is critical for reliable output.

```dockerfile
FROM hf.co/IndexTeam/Index-Translate-9B-GGUF:Q4_K_M

# CRITICAL: Set greedy decoding for deterministic translation.
# The model card explicitly recommends temperature=0.
PARAMETER temperature 0

# CRITICAL: The model expects a specific prompt structure.
# This template wraps your input, but the full prompt (with translation instructions) 
# must be constructed in your application code (see Step 3).
TEMPLATE """{{ .Prompt }}"""

# Set a reasonable context window. Prompt and output both count toward this limit.
PARAMETER num_ctx 4096
```

3.  Build the custom model in Ollama using the `create` command:
    ```bash
    ollama create index-translate-9b -f Modelfile
    ```
    You can now run your properly configured model with `ollama run index-translate-9b`.

### 📝 Step 3: Construct Prompts Using the Official Template

This is the most crucial step for efficiency. The model is trained on a specific **Chinese-language instruction template** and expects it exactly. Sending a plain English command like "Translate this" will yield poor results.

Your application code must build the full prompt string before sending it to Ollama.

**For standard, unconstrained translation**, the template is:

```text
请将以下{source-language}文本翻译为{target-language}，直接输出翻译结果，不要进行任何解释。
{source-text}
```

**How to use it in practice (example for a Python application):**

```python
def build_translation_prompt(source_text, target_lang_name, source_lang_name="中文"):
    # Note: The model card suggests using full language names in Chinese.
    # e.g., "英语" (English), "法语" (French), "西班牙语" (Spanish), "日语" (Japanese), "中文" (Chinese)
    prompt_template = f"请将以下{source_lang_name}文本翻译为{target_lang_name}，直接输出翻译结果，不要进行任何解释。\n{source_text}"
    return prompt_template

# Example: Translate from English to French
text_to_translate = "Hello, how can I help you today?"
prompt = build_translation_prompt(text_to_translate, target_lang_name="法语")
# Now, send 'prompt' as the input to your ollama model.
# The model will return ONLY the French translation.
```

**For constrained translation (advanced)**, such as enforcing a glossary, the model uses a more complex `instTrans` structure with separate sections for hard and soft requirements. The official client code on GitHub provides a full reference for this.

### 🚀 Step 4: Best Practices for Efficient Operation

*   **Always Use `temperature=0`**: This is non-negotiable for consistent, high-quality translation. The Modelfile above handles this.
*   **Disable "Thinking"**: The model has a reasoning mode that must be disabled for translation. The official client does this by setting `enable_thinking: false` in the chat template. If your Ollama version or client doesn't handle this automatically, you may need to strip out `…` tokens from the response, as shown in the official Python example.
*   **Use Chinese Language Names in Prompts**: The client maps short language codes to Chinese names. For optimal results, use the full Chinese name for your target language in the prompt (e.g., `法语` for French, `西班牙语` for Spanish).
*   **Manage Context Length**: Remember that the prompt length, source text, and generated output all count toward the `num_ctx` limit you set. For long documents, you may need to increase this value, but be mindful of memory usage.
*   **Start with the 9B Model**: For a kiosk, the 9B model (quantized to Q4) is often the "sweet spot" for quality versus resource usage, fitting comfortably on a 16GB GPU.

By following these steps—pulling the right model, enforcing `temperature=0` with a custom Modelfile, and using the official Chinese prompt template—you will be using Index-Translate as it was designed, ensuring reliable and high-quality translations for your kiosk.

If you decide to test a specific model size or run into issues with the prompt format, let me know and I can provide more tailored examples.


------------------------------------------------------------



Table 32:Core languages: 22 entries, including English and Chinese. Alternate identifiers are grouped together.
Code(s)
Language / variety
Code(s)
Language / variety
en, eng_Latn
English
zh, zho_Hans
Chinese
de
German
fr
French
es
Spanish
ja
Japanese
ko
Korean
pt
Portuguese
ru
Russian
ar
Arabic
it
Italian
nl
Dutch
pl
Polish
ro
Romanian
sv
Swedish
tr
Turkish
hi
Hindi
vi
Vietnamese
th
Thai
id
Indonesian
ms
Malay
fil
Filipino
 
Table 33:Additional languages and varieties: 128 entries. Alternate identifiers are grouped together.
Code(s)
Language / variety
Code(s)
Language / variety
ukr_Cyrl
Ukrainian
fas_Arab, pes_Arab
Persian
ces_Latn
Czech
ell_Grek
Greek
dan_Latn
Danish
hun_Latn
Hungarian
fin_Latn
Finnish
nob_Latn
Norwegian Bokmål
slk_Latn
Slovak
bul_Cyrl
Bulgarian
bos_Latn
Bosnian
cat_Latn
Catalan
ben_Beng
Bengali
heb_Hebr
Hebrew
lit_Latn
Lithuanian
slv_Latn
Slovenian
ekk_Latn
Estonian
als_Latn
Albanian
lvs_Latn
Latvian
azj_Latn
Azerbaijani
hrv_Latn
Croatian
tam_Taml
Tamil
npi_Deva
Nepali
urd_Arab
Urdu (Arabic script)
mkd_Cyrl
Macedonian
srp_Cyrl
Serbian (Cyrillic)
mar_Deva
Marathi
kat_Geor
Georgian
mal_Mlym
Malayalam
kaz_Cyrl
Kazakh
isl_Latn
Icelandic
glg_Latn
Galician
kan_Knda
Kannada
ary_Arab
Moroccan Arabic
guj_Gujr
Gujarati
bel_Cyrl
Belarusian
afr_Latn
Afrikaans
hye_Armn
Armenian
khk_Cyrl
Mongolian
khm_Khmr
Khmer
eus_Latn
Basque
mya_Mymr
Burmese
lat_Latn
Latin
uzn_Cyrl
Uzbek (Cyrillic)
tel_Telu
Telugu
ory_Orya
Odia
nno_Latn
Norwegian Nynorsk
uzn_Latn
Uzbek (Latin)
swh_Latn
Swahili
sin_Sinh
Sinhala
kir_Cyrl
Kyrgyz
som_Latn
Somali
pan_Guru
Punjabi
arz_Arab
Egyptian Arabic
cym_Latn
Welsh
nrm_Latn
Norman
pbt_Arab
Pashto
gle_Latn
Irish
srp_Latn
Serbian (Latin)
hau_Latn
Hausa
ckb_Arab
Central Kurdish
mlt_Latn
Maltese
yue_Hani, yue_Hant
Cantonese
tgk_Cyrl
Tajik
kmr_Latn
Northern Kurdish
bew_Latn
Betawi
amh_Ethi
Amharic
lao_Laoo
Lao
ltz_Latn
Luxembourgish
fry_Latn
Frisian
div_Thaa
Dhivehi
epo_Latn
Esperanto
kin_Latn
Kinyarwanda
ars_Arab
Najdi Arabic
fao_Latn
Faroese
plt_Latn
Malagasy
asm_Beng
Assamese
snd_Arab
Sindhi
xho_Latn
Xhosa
tuk_Latn
Turkmen
hat_Latn
Haitian Creole
gla_Latn
Scottish Gaelic
ceb_Latn
Cebuano
ydd_Hebr
Yiddish
jav_Latn
Javanese
bak_Cyrl
Bashkir
pap_Latn
Papiamento
mri_Latn
Māori
uig_Arab
Uyghur
tat_Cyrl
Tatar
bod_Tibt
Tibetan
mww_Latn
White Hmong
hyw_Armn
Western Armenian
yor_Latn
Yoruba
zul_Latn
Zulu
sdh_Arab
Southern Kurdish
smo_Latn
Samoan
cos_Latn
Corsican
hif_Latn
Fiji Hindi
sun_Latn
Sundanese
nya_Latn
Chichewa
ibo_Latn
Igbo
haw_Latn
Hawaiian
sot_Latn
Sesotho
lus_Latn
Mizo
sna_Latn
Shona
chv_Cyrl
Chuvash
azb_Arab
South Azerbaijani
roh_Latn
Romansh
run_Latn
Kirundi
hin_Latn
Hindi (Latin)
sah_Cyrl
Yakut
tir_Ethi
Tigrinya
ast_Latn
Asturian
oci_Latn
Occitan
cnh_Latn
Hakha Chin
sme_Latn
Northern Sami
nds_Latn
Low German
oss_Cyrl
Ossetian
urd_Latn
Urdu (Latin)
gsw_Latn
Swiss German
anp_Deva
Angika
apc_Arab
Levantine Arabic
gaz_Latn
Oromo
nap_Latn
Neapolitan
hsb_Latn
Upper Sorbian
hil_Latn
Hiligaynon
kal_Latn
Greenlandic