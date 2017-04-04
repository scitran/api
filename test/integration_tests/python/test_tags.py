def test_tags(data_builder, as_admin):
    project = data_builder.create_project()

    tag = 'test_tag'
    new_tag = 'new_test_tag'
    other_tag = 'other_test_tag'
    short_tag = 't'
    too_long_tag = 'this_tag_is_much_too_long_only_allow_32_characters'

    tags_path = '/projects/' + project + '/tags'
    tag_path = tags_path + '/' + tag
    new_tag_path = tags_path + '/' + new_tag
    other_tag_path = tags_path + '/' + other_tag
    short_tag_path = tags_path + '/' + short_tag

    # Add tag and verify
    r = as_admin.get(tag_path)
    assert r.status_code == 404
    r = as_admin.post(tags_path, json={'value': tag})
    assert r.ok
    r = as_admin.get(tag_path)
    assert r.ok
    assert r.json() == tag

    # Add new tag and verify
    r = as_admin.post(tags_path, json={'value': new_tag})
    assert r.ok
    # Add a duplicate tag, returns 404
    r = as_admin.post(tags_path, json={'value': new_tag})
    assert r.status_code == 409
    r = as_admin.get(new_tag_path)
    assert r.ok
    assert r.json() == new_tag

    # Add short tag and verify
    r = as_admin.post(tags_path, json={'value': short_tag})
    assert r.ok
    # Add too long tag and verify
    r = as_admin.post(tags_path, json={'value': too_long_tag})
    assert r.status_code == 400

    # Attempt to update tag, returns 404
    r = as_admin.put(tag_path, json={'value': new_tag})
    assert r.status_code == 404

    # Update existing tag to other_tag
    r = as_admin.get(other_tag_path)
    assert r.status_code == 404
    r = as_admin.put(tag_path, json={'value': other_tag})
    assert r.ok
    r = as_admin.get(other_tag_path)
    assert r.ok
    assert r.json() == other_tag
    r = as_admin.get(tag_path)
    assert r.status_code == 404

    # Cleanup
    r = as_admin.delete(other_tag_path)  # url for 'DELETE' is the same as the one for 'GET'
    assert r.ok
    r = as_admin.get(other_tag_path)
    assert r.status_code == 404
    r = as_admin.delete(new_tag_path)  # url for 'DELETE' is the same as the one for 'GET'
    assert r.ok
    r = as_admin.get(new_tag_path)
    assert r.status_code == 404
    r = as_admin.delete(short_tag_path)  # url for 'DELETE' is the same as the one for 'GET'
    assert r.ok
    r = as_admin.get(short_tag_path)
    assert r.status_code == 404
