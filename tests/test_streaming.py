"""Nested model/parser traces must not masquerade as pipeline transitions."""
from resume_agent.api.streaming import StreamTranslator


def test_nested_model_and_routing_events_do_not_end_pipeline_node():
    translator = StreamTranslator()
    start = translator.translate({'event': 'on_chain_start', 'name': 'extract_jd', 'run_id': 'outer',
                                  'metadata': {'langgraph_node': 'extract_jd'}})
    assert [e.type for e in start] == ['node_start', 'log_line']
    for name, event in [('ChatModel', 'on_chat_model_end'), ('JsonOutputParser', 'on_parser_end'),
                        ('_route_after_gaps', 'on_chain_end')]:
        assert translator.translate({'event': event, 'name': name,
                                     'metadata': {'langgraph_node': 'extract_jd'},
                                     'data': {'output': {}}}) == []
    end = translator.translate({'event': 'on_chain_end', 'name': 'extract_jd', 'run_id': 'outer',
                                'metadata': {'langgraph_node': 'extract_jd'}, 'data': {'output': {}}})
    assert [e.type for e in end] == ['node_end', 'log_line']
    assert end[0].duration_ms is not None
