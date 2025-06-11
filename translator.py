from typing import Optional, List
from typing_extensions import TypedDict
from langchain_core.runnables import Runnable
from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, START, StateGraph
from langchain_core.runnables.config import RunnableConfig


TRANSLATION_PROMPT = """
    Translate the following text from {source_language} to {target_language}: \
    <text> \
    {text}
    </text> \
    Translate every part of the text without changing the meaning or forgetting anything. \
    Do NOT use any kind of formatting if they are not present in the original text. \
    Do NOT return <text> or </text> tags. \
    Return ONLY the translated text. Do NOT add any other explanation \
"""


class TranslatorState(TypedDict):
    text: str
    target_language: str
    source_language: str
    translation: Optional[str]


def translate_text(state: TranslatorState, config: RunnableConfig) -> TranslatorState:
    configurable = config.get("configurable", {})
    translator = configurable.get("translator")
    if translator is None:
        raise ValueError("Translator is not provided in the config['configurable']")
    input_dict = {
        "text": state["text"],
        "source_language": state["source_language"],
        "target_language": state["target_language"],
    }
    translation = translator.invoke(input_dict).content
    return {**state, "translation": translation.strip() if translation else ""}


def compile_graph(graph: StateGraph):
    graph.add_node("Translator", translate_text)
    graph.add_edge(START, "Translator")
    graph.add_edge("Translator", END)
    return graph.compile()


class Translator:
    """A class to handle translation tasks using a language model."""

    def __init__(self, llm: Runnable, default_source_language: str = "english", default_target_language: str = "italian"):
        self.llm = llm
        self.default_source_language = default_source_language
        self.default_target_language = default_target_language
        translator = self._define_translator()
        self.graph = compile_graph(StateGraph(TranslatorState))
        self.config = {
            "configurable": {
                "translator": translator,
            }
        }

    def _define_translator(self) -> Runnable:
        translator_template = PromptTemplate.from_template(TRANSLATION_PROMPT)
        return translator_template | self.llm

    def translate(
        self, text: List[str], source_language: Optional[str] = None, target_language: Optional[str] = None
    ) -> List[str]:
        """
        Translate a given text to a target language. If the source language is already the same as the target,
        no translation is performed.

        Args:
            text (List[str]): The input text to translate.
            source_language (str): The source language code (e.g., 'en', 'it').
            target_language (str): The target language code (e.g., 'en', 'it').

        Returns:
            Optional[str]: The translated text or None if input is empty or no translation needed.
        """
        if not text or not isinstance(text, list) or not any(t.strip() for t in text):
            return []

        source_language = source_language or self.default_source_language
        target_language = target_language or self.default_target_language
        
        if source_language == target_language:
            return text
        
        inputs = [
            {
                "text": t,
                "source_language": source_language,
                "target_language": target_language,
                "translation": None,
            }
            for t in text
        ]

        outputs = self.graph.batch(inputs, config=self.config)  # type: ignore[arg-type]
        return [o.get("translation", "") for o in outputs]
