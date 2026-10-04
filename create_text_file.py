def create_text_file(filename, content):
    """
    Crée un fichier texte avec le nom et le contenu spécifiés.
    """
    with open(filename, 'w') as file:
        file.write(content)

if __name__ == '__main__':
    filename = 'example.txt'
    content = 'Ceci est un exemple de fichier texte.'
    create_text_file(filename, content)