# EPUB Translator
This project provides a set of tools for translating the text content of EPUB files using language models.

# Features
- Extracts text from EPUB files.
- Translates text using language models.
- Preserves the original structure and formatting of the EPUB files.

# Requirements
- Python 3.9 or higher
- Required Python packages listed in `requirements.txt`
- An EPUB file to translate
- A language model API key (if using an external translation service)

# Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/GiuseppeBellamacina/EPUB-Translator.git
   cd EPUB-Translator
   ```
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

# Usage

1. Place your EPUB file in the project directory.
2. Update the `main.ipynb` file to specify the correct EPUB file name.
3. Run the `main.ipynb` notebook to perform the translation.
   ```bash
   jupyter nbconvert --to notebook --execute main.ipynb
   ```

# Configuration
You can configure the translation settings BY instantiating your proper `Translator` class in the `main.ipynb` file. Adjust the parameters such as source language, target language, and translation service as needed.
# Example
```python
from langchain_openai import ChatOpenAI
from translator import Translator

llm = ChatOpenAI(
    model_name='gpt-3.5-turbo',
    temperature=0.0
)

translator = Translator(
    llm=llm,
    default_source_language='spanish',
    default_target_language='chinese',
)
```

Remember to set your API keys in the environment variables or directly in the code if necessary.
