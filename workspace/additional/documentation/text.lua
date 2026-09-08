function Link(el)
  local label = pandoc.utils.stringify(el.content)
  if label == '¶' or label == '[source]' then return {} end
  return el.content
end

function Image(el)
  local alt = pandoc.utils.stringify(el.caption)
  return pandoc.Str('[Image' .. (alt ~= '' and ': ' .. alt or '') .. '; see original HTML]')
end

function Div(el)
  if el.classes:includes('article-footer') then return {} end
  return el.content
end

function Span(el) return el.content end

function Table(el)
  local blocks = pandoc.Blocks(el.caption.long)
  blocks:insert(pandoc.Para({pandoc.Str(
    'Table cells follow in source order. For column alignment and merged cells, see original HTML.'
  )}))
  local row_number = 0
  local function append_rows(rows)
    for _, row in ipairs(rows) do
      row_number = row_number + 1
      blocks:insert(pandoc.Para({pandoc.Str('Row ' .. row_number .. ':')}))
      local cells = pandoc.List()
      for _, cell in ipairs(row.cells) do cells:insert(cell.contents) end
      blocks:insert(pandoc.BulletList(cells))
    end
  end
  append_rows(el.head.rows)
  for _, body in ipairs(el.bodies) do
    append_rows(body.head)
    append_rows(body.body)
  end
  append_rows(el.foot.rows)
  return blocks
end

function RawBlock(el)
  return pandoc.Para({pandoc.Str('[Embedded content; see original HTML]')})
end

function RawInline(el)
  return pandoc.Str('[Embedded content; see original HTML]')
end

function Pandoc(doc)
  local path = '/run/dojo/share/doc/' .. os.getenv('DOC_HTML_RELATIVE')
  doc.blocks:insert(1, pandoc.Para({pandoc.Str(
    'Text companion: links and visual layout are omitted. Open the original HTML for full context:'
  )}))
  doc.blocks:insert(2, pandoc.CodeBlock("w3m '" .. path:gsub("'", "'\\''") .. "'"))
  return doc
end
