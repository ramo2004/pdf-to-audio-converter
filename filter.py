import jenkspy

def parse_ocr_data(ocr_annotation):
    words, sizes = [], []
    for page in ocr_annotation.pages:
        for block in page.blocks:
            for para in block.paragraphs:
                for word in para.words:
                    text = "".join(symbol.text for symbol in word.symbols)
                    ys = [v.y for v in word.bounding_box.vertices]
                    words.append(text)
                    sizes.append(max(ys) - min(ys))
    return words, sizes

def cluster_body_sizes(sizes, n_classes=3):
    breaks = jenkspy.jenks_breaks(sizes, nb_class=n_classes)
    return breaks

def filter_body_words(words_and_sizes, breaks):
    return [w for (w, s) in words_and_sizes if breaks[1] < s <= breaks[2]]
