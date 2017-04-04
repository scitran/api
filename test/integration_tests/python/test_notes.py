def test_notes(data_builder, as_admin):
    project = data_builder.create_project()

    # Add a note
    note_text = 'test note'
    r = as_admin.post('/projects/' + project + '/notes', json={'text': note_text})
    assert r.ok

    # Verify note is present in project
    r = as_admin.get('/projects/' + project)
    assert r.ok
    assert len(r.json()['notes']) == 1
    note = r.json()['notes'][0]['_id']

    r = as_admin.get('/projects/' + project + '/notes/' + note)
    assert r.ok
    assert r.json()['text'] == note_text

    # Modify note
    note_text_2 = 'modified note'
    r = as_admin.put('/projects/' + project + '/notes/' + note, json={'text': note_text_2})
    assert r.ok

    # Verify modified note
    r = as_admin.get('/projects/' + project + '/notes/' + note)
    assert r.ok
    assert r.json()['text'] == note_text_2

    # Delete note
    r = as_admin.delete('/projects/' + project + '/notes/' + note)
    assert r.ok

    r = as_admin.get('/projects/' + project + '/notes/' + note)
    assert r.status_code == 404


def test_analysis_notes(data_builder, file_form, as_admin):
    acquisition = data_builder.create_acquisition()

    # create acquisition analysis
    file_name = 'one.csv'
    r = as_admin.post('/acquisitions/' + acquisition + '/analyses', files=file_form(
        file_name, meta={'label': 'test analysis', 'inputs': [{'name': file_name}]}))
    assert r.ok
    analysis = r.json()['_id']

    # create analysis note
    note_text = 'test note'
    r = as_admin.post('/acquisitions/' + acquisition + '/analyses/' + analysis + '/notes', json={
        'text': note_text
    })
    assert r.ok

    # delete acquisition analysis
    r = as_admin.delete('/acquisitions/' + acquisition + '/analyses/' + analysis)
    assert r.ok
