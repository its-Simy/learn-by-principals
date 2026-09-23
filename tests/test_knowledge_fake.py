from core.providers.knowledge.base import GroundedAnswer, KnowledgeProvider, ProviderState
from tests.fakes.fake_knowledge import FakeKnowledge


def test_fake_knowledge_smoke(tmp_path):
    kp = FakeKnowledge(out_dir=tmp_path / "out", answer_text="Pointers hold addresses.")
    assert isinstance(kp, KnowledgeProvider)
    nb = kp.ensure_notebook("CSE220")
    assert kp.ensure_notebook("CSE220") == nb
    assert kp.notebooks == {"BrightLearn/CSE220": nb}

    syllabus = tmp_path / "syllabus.pdf"
    syllabus.write_text("Grading: exams 60%, labs 40%")
    source_id = kp.add_file(nb, syllabus)
    assert [s.source_id for s in kp.list_sources(nb)] == [source_id]

    answer = kp.query(nb, "What is the grading breakdown?")
    assert isinstance(answer, GroundedAnswer)
    assert answer.text == "Pointers hold addresses."
    assert answer.citations[0].source_id == source_id
    assert "exams 60%" in kp.source_fulltext(source_id)

    assert kp.generate_quiz(nb)["questions"]
    assert kp.generate_audio(nb, "# brief", "brief", "short").read_bytes().startswith(b"ID3")
    assert kp.generate(nb, "report", {}).exists()
    assert kp.health() is ProviderState.AVAILABLE

    kp.remove_source(source_id)
    assert kp.list_sources(nb) == []
